// Tarjem TV — the transparent full-screen layer that draws the Arabic subtitles.
// Several blocks can be on screen at once; each sits on its English original, and
// blocks are pushed apart so they never overlap. Character names get their own colour.

package com.tarjem.tv

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.text.SpannableStringBuilder
import android.text.Spanned
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
}

class CaptionLayer(context: Context) : FrameLayout(context)
{
	private val boxes = mutableListOf<TextView>()
	private var style = CaptionStyle()
	private var lastItems: List<CapItem>? = null

	init
	{
		isClickable = false
		isFocusable = false
	}

	fun setStyle(s: CaptionStyle)
	{
		style = s
		lastItems?.let { show(it) }
	}

	private fun screenW() = if(width > 0) width else resources.displayMetrics.widthPixels
	private fun screenH() = if(height > 0) height else resources.displayMetrics.heightPixels
	private fun scale(): Float = screenH().toFloat() / 1080f

	private fun box(i: Int): TextView
	{
		while(boxes.size <= i)
		{
			val tv = TextView(context).apply {
				gravity = Gravity.CENTER
				textDirection = View.TEXT_DIRECTION_ANY_RTL
				layoutDirection = View.LAYOUT_DIRECTION_RTL
				setLineSpacing(0f, 1.12f)
				visibility = View.GONE
			}
			addView(tv, LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT))
			boxes.add(tv)
		}
		return boxes[i]
	}

	private fun styleBox(tv: TextView)
	{
		val s = scale()
		tv.setTextColor(style.fg)
		tv.setTextSize(TypedValue.COMPLEX_UNIT_PX, style.size * s)
		val family = when(style.font)
		{
			"serif" -> "serif"
			"condensed" -> "sans-serif-condensed"
			else -> "sans-serif"
		}
		tv.typeface = Typeface.create(family, if(style.bold) Typeface.BOLD else Typeface.NORMAL)
		val alpha = (style.bgAlpha * 255).roundToInt().coerceIn(0, 255)
		tv.background = GradientDrawable().apply {
			cornerRadius = style.radius * s
			setColor(Color.argb(alpha, Color.red(style.bg), Color.green(style.bg), Color.blue(style.bg)))
		}
		if(style.outline || style.bgAlpha < 0.5f)
			tv.setShadowLayer(4f * s, 0f, 1.5f * s, Color.BLACK)
		else
			tv.setShadowLayer(0f, 0f, 0f, 0)
		val padH = (18 * s).roundToInt()
		val padV = (8 * s).roundToInt()
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
				sb.append(sp).append(": ")
				sb.setSpan(ForegroundColorSpan(style.speaker), start, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
				sb.setSpan(StyleSpan(Typeface.BOLD), start, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
			}
			sb.append(line.text)
		}
		return sb
	}

	/** Shows [items]; each item's rect is where the game's own subtitle is (normalised), null = bottom band. */
	fun show(items: List<CapItem>)
	{
		lastItems = items
		val w = screenW()
		val h = screenH()
		if(w == 0 || h == 0)
			return
		val maxW = (w * style.maxWidth).roundToInt()
		val margin = (w * 0.02f).roundToInt()
		val pad = (h * 0.008f)
		val wants = ArrayList<StackLayout.Want>()

		items.forEachIndexed { i, item ->
			val tv = box(i)
			styleBox(tv)
			tv.text = textOf(item)
			val r = item.rect
			val boxW: Int
			val bottom: Int
			val left: Int
			if(style.placement == "bottom" || r == null)
			{
				tv.minHeight = 0
				tv.maxWidth = maxW
				tv.measure(MeasureSpec.makeMeasureSpec(maxW, MeasureSpec.AT_MOST), MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED))
				boxW = tv.measuredWidth
				left = (w - boxW) / 2
				bottom = h - (h * style.bottomMargin).roundToInt()
			}
			else
			{
				// Same width as the English line (a little wider for padding), centred on it.
				boxW = min(maxW, max((w * 0.18f).roundToInt(), (r.w * w + pad * 4).roundToInt()))
				tv.minHeight = (r.h * h + pad * 2).roundToInt()
				left = (r.centerX * w - boxW / 2f).roundToInt().coerceIn(margin, max(margin, w - margin - boxW))
				// Bottom on the English block's bottom: a taller Arabic box grows upwards.
				bottom = min(h, (r.bottom * h + pad).roundToInt())
			}
			tv.measure(MeasureSpec.makeMeasureSpec(boxW, MeasureSpec.EXACTLY), MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED))
			wants.add(StackLayout.Want(left, boxW, tv.measuredHeight, bottom))
		}

		val placed = StackLayout.place(wants, h, (h * 0.006f).roundToInt())
		placed.forEachIndexed { i, p ->
			val tv = boxes[i]
			val lp = tv.layoutParams as LayoutParams
			lp.width = p.width
			lp.height = LayoutParams.WRAP_CONTENT
			lp.gravity = Gravity.TOP or Gravity.START
			lp.leftMargin = p.left
			lp.topMargin = p.top
			tv.layoutParams = lp
			if(tv.visibility != View.VISIBLE)
			{
				tv.alpha = 0f
				tv.visibility = View.VISIBLE
				tv.animate().alpha(1f).setDuration(110).start()
			}
		}
		for(i in items.size until boxes.size)
			hideBox(boxes[i])
	}

	private fun hideBox(tv: TextView)
	{
		if(tv.visibility != View.VISIBLE)
			return
		tv.animate().cancel()
		tv.animate().alpha(0f).setDuration(140).withEndAction { tv.visibility = View.GONE }.start()
	}

	fun hide()
	{
		lastItems = null
		boxes.forEach { hideBox(it) }
	}
}
