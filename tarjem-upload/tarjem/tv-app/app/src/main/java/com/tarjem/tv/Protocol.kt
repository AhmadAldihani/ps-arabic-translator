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
	/** Text size in pixels on a 1080-line screen; scaled to the real overlay height. */
	val size: Float = 34f,
	val fg: Int = 0xFFFFFFFF.toInt(),
	val bg: Int = 0xFF101018.toInt(),
	/** 0 = transparent box (text only, with outline), 1 = solid box. */
	val bgAlpha: Float = 0.88f,
	/** "sans", "serif" or "condensed". */
	val font: String = "sans",
	val bold: Boolean = true,
	/** "cover" = on top of the game's own subtitle, "bottom" = fixed band at the bottom. */
	val placement: String = "cover",
	val radius: Float = 14f,
	/** Distance from the bottom edge in "bottom" mode, as a fraction of screen height. */
	val bottomMargin: Float = 0.07f,
	/** Widest the box may get, as a fraction of screen width. */
	val maxWidth: Float = 0.86f,
	val outline: Boolean = true,
	/** Colour of the character name in "Name: line" subtitles. */
	val speaker: Int = 0xFFF5B841.toInt()
)
{
	fun merge(o: JSONObject): CaptionStyle = CaptionStyle(
		size = o.optDouble("size", size.toDouble()).toFloat().coerceIn(12f, 120f),
		fg = o.optString("fg").let { if(it.isEmpty()) fg else Protocol.parseColor(it) ?: fg },
		bg = o.optString("bg").let { if(it.isEmpty()) bg else Protocol.parseColor(it) ?: bg },
		bgAlpha = o.optDouble("bgAlpha", bgAlpha.toDouble()).toFloat().coerceIn(0f, 1f),
		font = o.optString("font", font).ifEmpty { font },
		bold = o.optBoolean("bold", bold),
		placement = o.optString("placement", placement).let { if(it == "cover" || it == "bottom") it else placement },
		radius = o.optDouble("radius", radius.toDouble()).toFloat().coerceIn(0f, 60f),
		bottomMargin = o.optDouble("bottomMargin", bottomMargin.toDouble()).toFloat().coerceIn(0f, 0.5f),
		maxWidth = o.optDouble("maxWidth", maxWidth.toDouble()).toFloat().coerceIn(0.2f, 1f),
		outline = o.optBoolean("outline", outline),
		speaker = o.optString("speaker").let { if(it.isEmpty()) speaker else Protocol.parseColor(it) ?: speaker }
	)
}

/** One spoken line; [speaker] is the character name, drawn in its own colour. */
data class CapLine(val speaker: String?, val text: String)

/** One subtitle block on screen and where the game shows it. */
data class CapItem(val lines: List<CapLine>, val rect: NRect?)

sealed class Msg
{
	data class Hello(val name: String) : Msg()
	data class Show(val items: List<CapItem>, val ttlMs: Long) : Msg()
	data class Keep(val ttlMs: Long) : Msg()
	object Clear : Msg()
	data class Style(val patch: JSONObject) : Msg()
	object Ping : Msg()
	object Test : Msg()
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
		for(i in 0 until minOf(arr.length(), 8))
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
				out.add(CapItem(lines, parseRect(it)))
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
