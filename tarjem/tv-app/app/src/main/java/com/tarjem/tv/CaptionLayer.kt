// Tarjemni TV — the transparent full-screen layer that draws the Arabic subtitles.
// Several blocks can be on screen at once; each sits exactly on its English original (same size),
// blocks are pushed apart so they never overlap, and character names get their own colour.

package com.tarjem.tv

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.drawable.GradientDrawable
import android.text.Layout
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.StaticLayout
import android.text.TextDirectionHeuristics
import android.text.TextPaint
import android.text.style.ForegroundColorSpan
import android.text.style.StyleSpan
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.TextView
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** Pure layout maths (no views), unit tested. Boxes are in screen pixels. */
object StackLayout
{
	data class Want(val left: Int, val width: Int, val height: Int, val bottom: Int)
	data class Placed(val left: Int, val top: Int, val width: Int, val height: Int)
	{
		val right get() = left + width
		val bottom get() = top + height
	}

	/**
	 * Places each box with its bottom edge at [Want.bottom] if it can; a box that would overlap a box
	 * already placed below it (and overlapping horizontally) is moved up just above it.
	 * Result is in the same order as [wants].
	 */
	fun place(wants: List<Want>, screenH: Int, gap: Int): List<Placed>
	{
		val order = wants.indices.sortedByDescending { wants[it].bottom }
		val placed = arrayOfNulls<Placed>(wants.size)
		val done = mutableListOf<Placed>()
		for(i in order)
		{
			val w = wants[i]
			var bottom = min(w.bottom, screenH)
			var moved = true
			var guard = 0
			while(moved && guard++ < 20)
			{
				moved = false
				for(p in done)
				{
					val top = bottom - w.height
					val hOverlap = w.left < p.right && w.left + w.width > p.left
					val vOverlap = top < p.bottom + gap && bottom > p.top - gap
					if(hOverlap && vOverlap)
					{
						bottom = p.top - gap
						moved = true
					}
				}
			}
			val top = max(0, bottom - w.height)
			val pl = Placed(w.left, top, w.width, w.height)
			placed[i] = pl
			done.add(pl)
		}
		return placed.map { it!! }
	}

	/** Text size (px) for Arabic covering an English line of [lineHeightPx]. */
	fun autoTextSize(lineHeightPx: Float, scale: Float): Float = (lineHeightPx * 0.80f * scale).coerceIn(12f, 160f)
}

/** TextView that can draw a coloured outline around its letters (under the fill). */
class OutlinedTextView(context: Context) : TextView(context)
{
	var outlineWidth = 0f
	var outlineColor = Color.BLACK
	private var strokeLayout: StaticLayout? = null
	private var strokeKey: List<Any?>? = null

	override fun onDraw(canvas: Canvas)
	{
		val l = layout
		if(outlineWidth > 0f && l != null)
		{
			val key = listOf(text.toString(), l.width, textSize, typeface, outlineWidth, outlineColor, lineSpacingMultiplier)
			if(key != strokeKey)
			{
				val p = TextPaint(paint)
				p.style = Paint.Style.STROKE
				p.strokeWidth = outlineWidth
				p.strokeJoin = Paint.Join.ROUND
				p.color = outlineColor
				p.clearShadowLayer()
				val plain = text.toString()
				strokeLayout = StaticLayout.Builder.obtain(plain, 0, plain.length, p, l.width)
					.setAlignment(Layout.Alignment.ALIGN_CENTER)
					.setLineSpacing(lineSpacingExtra, lineSpacingMultiplier)
					.setIncludePad(includeFontPadding)
					.setTextDirection(TextDirectionHeuristics.ANYRTL_LTR)
					.build()
				strokeKey = key
			}
			val sl = strokeLayout
			if(sl != null)
			{
				val avail = height - extendedPaddingTop - extendedPaddingBottom
				val voff = max(0, (avail - l.height) / 2)
				canvas.save()
				canvas.translate(compoundPaddingLeft.toFloat(), (extendedPaddingTop + voff).toFloat())
				sl.draw(canvas)
				canvas.restore()
			}
		}
		super.onDraw(canvas)
	}
}

class CaptionLayer(context: Context) : FrameLayout(context)
{
	private val boxes = mutableListOf<OutlinedTextView>()
	private var style = CaptionStyle()
	private var lastItems: List<CapItem>? = null

	init
	{
		isClickable = false
		isFocusable = false
		// Positions are absolute screen coordinates, whatever the TV's language direction.
		layoutDirection = View.LAYOUT_DIRECTION_LTR
	}

	fun setStyle(s: CaptionStyle)
	{
		style = s
		lastItems?.let { show(it) }
	}

	private fun screenW() = if(width > 0) width else resources.displayMetrics.widthPixels
	private fun screenH() = if(height > 0) height else resources.displayMetrics.heightPixels
	private fun scale(): Float = screenH().toFloat() / 1080f

	private fun box(i: Int): OutlinedTextView
	{
		while(boxes.size <= i)
		{
			val tv = OutlinedTextView(context).apply {
				gravity = Gravity.CENTER
				textDirection = View.TEXT_DIRECTION_ANY_RTL
				layoutDirection = View.LAYOUT_DIRECTION_RTL
				includeFontPadding = false
				visibility = View.GONE
			}
			addView(tv, LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT))
			boxes.add(tv)
		}
		return boxes[i]
	}

	private fun styleBox(tv: OutlinedTextView, textPx: Float)
	{
		val s = scale()
		tv.setTextColor(style.fg)
		tv.setTextSize(TypedValue.COMPLEX_UNIT_PX, textPx)
		tv.typeface = Fonts.get(context, style.font, style.bold)
		// Arabic fonts like Cairo have very tall built-in line gaps; use an exact, compact line height.
		if(android.os.Build.VERSION.SDK_INT >= 28)
			tv.lineHeight = (textPx * 1.25f * style.lineSpacing / 1.12f).roundToInt()
		else
			tv.setLineSpacing(0f, style.lineSpacing)
		val alpha = (style.bgAlpha * 255).roundToInt().coerceIn(0, 255)
		tv.background = GradientDrawable().apply {
			cornerRadius = style.radius * s
			setColor(Color.argb(alpha, Color.red(style.bg), Color.green(style.bg), Color.blue(style.bg)))
		}
		if(style.shadow)
			tv.setShadowLayer(max(2f, textPx * 0.12f), 0f, textPx * 0.05f, Color.argb(230, 0, 0, 0))
		else
			tv.setShadowLayer(0f, 0f, 0f, 0)
		tv.outlineWidth = if(style.outline) style.outlineWidth * s else 0f
		tv.outlineColor = style.outlineColor
		val padH = (style.padX * s).roundToInt()
		val padV = (style.padY * s).roundToInt()
		tv.setPadding(padH, padV, padH, padV)
	}

	private fun textOf(item: CapItem): CharSequence
	{
		val sb = SpannableStringBuilder()
		item.lines.forEachIndexed { i, line ->
			if(i > 0)
				sb.append('\n')
			val sp = line.speaker
			if(!sp.isNullOrBlank())
			{
				val start = sb.length
				sb.append(sp).append(":")
				sb.setSpan(ForegroundColorSpan(style.speaker), start, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
				if(style.speakerBold)
					sb.setSpan(StyleSpan(android.graphics.Typeface.BOLD), start, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
				sb.append(if(style.speakerOwnLine) "\n" else " ")
			}
			sb.append(line.text)
		}
		return sb
	}

	/** Shows [items]; each item's rect is where the game's own subtitle is (normalised), null = band. */
	fun show(items: List<CapItem>)
	{
		lastItems = items
		val w = screenW()
		val h = screenH()
		if(w == 0 || h == 0)
			return
		val s = scale()
		val maxW = (w * style.maxWidth).roundToInt()
		val margin = (w * 0.02f).roundToInt()
		val pad = h * 0.006f
		val wants = ArrayList<StackLayout.Want>()
		val subIdx = ArrayList<Int>()

		items.forEachIndexed { i, item ->
			val tv = box(i)
			if(item.kind == "phone" && item.rect != null)
			{
				placePhone(tv, item, item.rect, w, h)
				return@forEachIndexed
			}
			tv.gravity = Gravity.CENTER
			subIdx.add(i)
			val textPx = if(style.autoSize && item.lineHeight > 0f)
				StackLayout.autoTextSize(item.lineHeight * h, style.sizeScale)
			else
				style.size * s
			styleBox(tv, textPx)
			tv.text = textOf(item)
			val r = item.rect
			val band = style.placement != "cover" || r == null
			var boxW: Int
			if(!band && style.widthMode == "match" && r != null)
			{
				// As wide as the English (plus the box padding), centred on it.
				boxW = min(maxW, max((w * 0.15f).roundToInt(), (r.w * w + style.padX * s * 2).roundToInt()))
			}
			else
			{
				tv.minHeight = 0
				tv.measure(MeasureSpec.makeMeasureSpec(maxW, MeasureSpec.AT_MOST), MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED))
				boxW = tv.measuredWidth
			}
			// Always cover the English lines completely.
			tv.minHeight = if(!band && r != null) (r.h * h + pad * 2 + style.padY * s * 2).roundToInt() else 0
			tv.measure(MeasureSpec.makeMeasureSpec(boxW, MeasureSpec.EXACTLY), MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED))
			// Fit the Arabic into the English's shape: as many lines as the English, a little wider at most,
			// then slightly smaller letters, so the box sits on the English like the game's own subtitle.
			if(!band && r != null)
			{
				val englishLines = max(item.lines.size, if(item.lineHeight > 0f) (r.h / item.lineHeight).roundToInt() else 1)
				val widest = min(maxW, (boxW * 1.35f).roundToInt())
				var px = textPx
				var guard = 0
				while(tv.lineCount > englishLines && guard++ < 12)
				{
					if(boxW < widest)
						boxW = min(widest, (boxW * 1.12f).roundToInt())
					else if(px > textPx * 0.8f)
					{
						px *= 0.94f
						tv.setTextSize(TypedValue.COMPLEX_UNIT_PX, px)
					}
					else
						break
					tv.measure(MeasureSpec.makeMeasureSpec(boxW, MeasureSpec.EXACTLY), MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED))
				}
			}
			val left: Int
			val bottom: Int
			when
			{
				!band && r != null -> {
					left = (r.centerX * w - boxW / 2f).roundToInt().coerceIn(margin, max(margin, w - margin - boxW))
					// Centred on the English block both ways; a taller Arabic box grows evenly up and down.
					val centreY = (r.y + r.h / 2f) * h
					bottom = min(h, (centreY + tv.measuredHeight / 2f).roundToInt())
				}
				style.placement == "top" -> {
					left = (w - boxW) / 2
					bottom = (h * style.bottomMargin).roundToInt() + tv.measuredHeight + i * (tv.measuredHeight + (8 * s).roundToInt())
				}
				else -> {
					left = (w - boxW) / 2
					bottom = h - (h * style.bottomMargin).roundToInt()
				}
			}
			wants.add(StackLayout.Want(left, boxW, tv.measuredHeight, bottom))
		}

		val placed = StackLayout.place(wants, h, (h * 0.006f).roundToInt())
		placed.forEachIndexed { k, p ->
			val tv = boxes[subIdx[k]]
			val lp = tv.layoutParams as LayoutParams
			lp.width = p.width
			lp.height = LayoutParams.WRAP_CONTENT
			// Absolute LEFT: with an Arabic TV language START means RIGHT and every box stuck to the right edge.
			lp.gravity = Gravity.TOP or Gravity.LEFT
			lp.leftMargin = p.left
			lp.rightMargin = 0
			lp.topMargin = p.top
			tv.layoutParams = lp
			if(tv.visibility != View.VISIBLE)
			{
				tv.animate().cancel()
				tv.alpha = 0f
				tv.visibility = View.VISIBLE
				tv.animate().alpha(1f).setDuration(70).start()
			}
			else
				tv.alpha = 1f
		}
		for(i in items.size until boxes.size)
			hideBox(boxes[i])
	}

	/** Phone text: exactly over the English, in the phone's own colours, so it looks part of the game. */
	private fun placePhone(tv: OutlinedTextView, item: CapItem, r: NRect, w: Int, h: Int)
	{
		val lineH = if(item.lineHeight > 0f) item.lineHeight * h else r.h * h
		val lines = max(1, (r.h * h / lineH).roundToInt())
		val padX = (lineH * 0.25f).roundToInt()
		val boxW = (r.w * w).roundToInt() + padX * 2
		val boxH = (r.h * h + lineH * 0.3f).roundToInt()
		tv.setTextColor(item.fg ?: Color.WHITE)
		tv.typeface = Fonts.get(context, style.font, false)
		tv.setShadowLayer(0f, 0f, 0f, 0)
		tv.outlineWidth = 0f
		tv.background = GradientDrawable().apply {
			cornerRadius = lineH * 0.18f
			setColor(item.bg ?: Color.BLACK)
		}
		tv.setPadding(padX, 0, padX, 0)
		tv.gravity = Gravity.CENTER_VERTICAL or Gravity.START
		tv.minHeight = boxH
		tv.text = item.lines.joinToString(" ") { it.text }
		var px = lineH * 0.74f
		if(android.os.Build.VERSION.SDK_INT >= 28)
			tv.lineHeight = (lineH * 0.98f).roundToInt()
		var guard = 0
		while(true)
		{
			tv.setTextSize(TypedValue.COMPLEX_UNIT_PX, px)
			tv.measure(MeasureSpec.makeMeasureSpec(boxW, MeasureSpec.EXACTLY), MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED))
			if(tv.lineCount <= lines || px < lineH * 0.45f || guard++ > 14)
				break
			px *= 0.93f
		}
		val lp = tv.layoutParams as LayoutParams
		lp.width = boxW
		lp.height = LayoutParams.WRAP_CONTENT
		lp.gravity = Gravity.TOP or Gravity.LEFT
		lp.leftMargin = (r.x * w).roundToInt() - padX
		lp.rightMargin = 0
		lp.topMargin = ((r.y + r.h / 2f) * h - tv.measuredHeight / 2f).roundToInt()
		tv.layoutParams = lp
		tv.animate().cancel()
		tv.alpha = 1f  // no fade: phone text must look fixed, not "popping"
		tv.visibility = View.VISIBLE
	}

	private fun hideBox(tv: TextView)
	{
		if(tv.visibility != View.VISIBLE)
			return
		tv.animate().cancel()
		tv.animate().alpha(0f).setDuration(110).withEndAction { tv.visibility = View.GONE }.start()
	}

	fun hide()
	{
		lastItems = null
		boxes.forEach { hideBox(it) }
	}
}
