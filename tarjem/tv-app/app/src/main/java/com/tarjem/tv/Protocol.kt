// Tarjem TV — wire protocol between the laptop (sender) and the TV (overlay).
// One JSON object per line over TCP. Kept free of android.* so it can be unit tested.

package com.tarjem.tv

import org.json.JSONObject

const val SERVER_PORT = 47800
const val DISCOVERY_PORT = 47801
const val DISCOVERY_REQUEST = "TARJEM_DISCOVER"

/** Normalised rectangle (0..1 of the screen). */
data class NRect(val x: Float, val y: Float, val w: Float, val h: Float)
{
	val right get() = x + w
	val bottom get() = y + h
	val centerX get() = x + w / 2f
}

data class CaptionStyle(
	val font: String = "cairo",
	/** Size the Arabic like the English line it covers (uses the line height the laptop measured). */
	val autoSize: Boolean = true,
	val sizeScale: Float = 1f,
	/** Text size in pixels on a 1080-line screen when [autoSize] is off. */
	val size: Float = 34f,
	val bold: Boolean = true,
	val fg: Int = 0xFFFFFFFF.toInt(),
	val bg: Int = 0xFF0B0F1A.toInt(),
	val bgAlpha: Float = 0.9f,
	val radius: Float = 12f,
	val padX: Float = 18f,
	val padY: Float = 8f,
	val outline: Boolean = false,
	val outlineColor: Int = 0xFF000000.toInt(),
	val outlineWidth: Float = 4f,
	val shadow: Boolean = true,
	val lineSpacing: Float = 1.12f,
	/** Colour of the character name in "Name: line" subtitles. */
	val speaker: Int = 0xFFF5B841.toInt(),
	val speakerBold: Boolean = true,
	val speakerOwnLine: Boolean = false,
	/** "cover" = on the game's own subtitle, "bottom"/"top" = fixed band. */
	val placement: String = "cover",
	/** "match" = as wide as the English, "fit" = as wide as the Arabic needs. */
	val widthMode: String = "match",
	val maxWidth: Float = 0.86f,
	val bottomMargin: Float = 0.07f
)
{
	fun merge(o: JSONObject): CaptionStyle
	{
		fun f(k: String, v: Float, lo: Float, hi: Float) = o.optDouble(k, v.toDouble()).toFloat().let { if(it.isNaN()) v else it.coerceIn(lo, hi) }
		fun c(k: String, v: Int) = o.optString(k).let { if(it.isEmpty()) v else Protocol.parseColor(it) ?: v }
		fun b(k: String, v: Boolean) = o.optBoolean(k, v)
		fun e(k: String, v: String, allowed: Set<String>) = o.optString(k, v).let { if(it in allowed) it else v }
		return CaptionStyle(
			font = e("font", font, setOf("cairo", "tajawal", "plex", "naskh", "system", "sans", "serif", "condensed")),
			autoSize = b("autoSize", autoSize),
			sizeScale = f("sizeScale", sizeScale, 0.3f, 3f),
			size = f("size", size, 10f, 140f),
			bold = b("bold", bold),
			fg = c("fg", fg),
			bg = c("bg", bg),
			bgAlpha = f("bgAlpha", bgAlpha, 0f, 1f),
			radius = f("radius", radius, 0f, 80f),
			padX = f("padX", padX, 0f, 120f),
			padY = f("padY", padY, 0f, 80f),
			outline = b("outline", outline),
			outlineColor = c("outlineColor", outlineColor),
			outlineWidth = f("outlineWidth", outlineWidth, 0f, 20f),
			shadow = b("shadow", shadow),
			lineSpacing = f("lineSpacing", lineSpacing, 0.8f, 2.2f),
			speaker = c("speaker", speaker),
			speakerBold = b("speakerBold", speakerBold),
			speakerOwnLine = b("speakerOwnLine", speakerOwnLine),
			placement = e("placement", placement, setOf("cover", "bottom", "top")),
			widthMode = e("widthMode", widthMode, setOf("match", "fit")),
			maxWidth = f("maxWidth", maxWidth, 0.2f, 1f),
			bottomMargin = f("bottomMargin", bottomMargin, 0f, 0.5f)
		)
	}
}

/** One spoken line; [speaker] is the character name, drawn in its own colour. */
data class CapLine(val speaker: String?, val text: String)

/** One subtitle block on screen, where the game shows it, and one English line's height (screen fraction). */
data class CapItem(
	val lines: List<CapLine>, val rect: NRect?, val lineHeight: Float = 0f,
	/** "phone" = text on the in-game phone: drawn exactly over it in the phone's own colours. */
	val kind: String = "sub", val bg: Int? = null, val fg: Int? = null,
)

sealed class Msg
{
	data class Hello(val name: String) : Msg()
	data class Show(val items: List<CapItem>, val ttlMs: Long) : Msg()
	data class Keep(val ttlMs: Long) : Msg()
	object Clear : Msg()
	data class Style(val patch: JSONObject) : Msg()
	object Ping : Msg()
	object Test : Msg()
	object Update : Msg()
}

object Protocol
{
	const val DEFAULT_TTL = 4000L

	fun parse(line: String): Msg?
	{
		val o = try { JSONObject(line) } catch(e: Exception) { return null }
		val ttl = o.optLong("ttl", DEFAULT_TTL).coerceIn(500L, 60_000L)
		return when(o.optString("t"))
		{
			"hello" -> Msg.Hello(o.optString("name", "laptop").take(60))
			"show" -> {
				val items = parseItems(o)
				if(items.isEmpty()) Msg.Clear else Msg.Show(items, ttl)
			}
			"keep" -> Msg.Keep(ttl)
			"clear" -> Msg.Clear
			"style" -> Msg.Style(o.optJSONObject("style") ?: o)
			"ping" -> Msg.Ping
			"test" -> Msg.Test
			"update" -> Msg.Update
			else -> null
		}
	}

	/** New form: {"items":[{"rect":[..],"lines":[{"s":"Jason","t":"..."}]}]}; old form: {"text","rect"}. */
	private fun parseItems(o: JSONObject): List<CapItem>
	{
		val arr = o.optJSONArray("items")
		if(arr == null)
		{
			val text = o.optString("text")
			return if(text.isBlank()) emptyList() else listOf(CapItem(listOf(CapLine(null, text.take(1000))), parseRect(o)))
		}
		val out = mutableListOf<CapItem>()
		for(i in 0 until minOf(arr.length(), 24))
		{
			val it = arr.optJSONObject(i) ?: continue
			val linesArr = it.optJSONArray("lines")
			val lines = mutableListOf<CapLine>()
			if(linesArr != null)
			{
				for(j in 0 until minOf(linesArr.length(), 8))
				{
					val l = linesArr.optJSONObject(j) ?: continue
					val t = l.optString("t").trim()
					if(t.isEmpty())
						continue
					val sp = l.optString("s").trim().ifEmpty { null }
					lines.add(CapLine(sp?.take(40), t.take(500)))
				}
			}
			else if(it.optString("text").isNotBlank())
				lines.add(CapLine(null, it.optString("text").take(1000)))
			if(lines.isNotEmpty())
				out.add(CapItem(lines, parseRect(it), it.optDouble("lh", 0.0).toFloat().let { h -> if(h.isNaN()) 0f else h.coerceIn(0f, 0.3f) },
					kind = it.optString("kind", "sub"), bg = parseColor(it.optString("bg")), fg = parseColor(it.optString("fg"))))
		}
		return out
	}

	private fun parseRect(o: JSONObject): NRect?
	{
		val a = o.optJSONArray("rect") ?: return null
		if(a.length() != 4)
			return null
		val x = a.optDouble(0, Double.NaN).toFloat()
		val y = a.optDouble(1, Double.NaN).toFloat()
		val w = a.optDouble(2, Double.NaN).toFloat()
		val h = a.optDouble(3, Double.NaN).toFloat()
		if(listOf(x, y, w, h).any { it.isNaN() } || w <= 0f || h <= 0f)
			return null
		return NRect(x.coerceIn(0f, 1f), y.coerceIn(0f, 1f), w.coerceIn(0f, 1f), h.coerceIn(0f, 1f))
	}

	/** "#RRGGBB" or "#AARRGGBB" → ARGB int. */
	fun parseColor(s: String): Int?
	{
		val hex = s.trim().removePrefix("#")
		val v = hex.toLongOrNull(16) ?: return null
		return when(hex.length)
		{
			6 -> (0xFF000000 or v).toInt()
			8 -> v.toInt()
			else -> null
		}
	}

	fun reply(type: String, fields: Map<String, Any?> = emptyMap()): String
	{
		val o = JSONObject()
		o.put("t", type)
		for((k, v) in fields)
			o.put(k, v)
		return o.toString()
	}
}
