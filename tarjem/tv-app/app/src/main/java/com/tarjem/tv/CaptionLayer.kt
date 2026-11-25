// Tarjem TV — the transparent full-screen layer that draws the Arabic subtitle.

package com.tarjem.tv

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.TextView
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

class CaptionLayer(context: Context) : FrameLayout(context)
{
	private val box = TextView(context)
	private var style = CaptionStyle()
	private var lastText: String? = null
	private var lastRect: NRect? = null

	init
	{
		isClickable = false
		isFocusable = false
		box.apply {
			gravity = Gravity.CENTER
			textDirection = View.TEXT_DIRECTION_ANY_RTL
			layoutDirection = View.LAYOUT_DIRECTION_RTL
			setLineSpacing(0f, 1.12f)
			visibility = View.GONE
		}
		addView(box, LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT))
		applyStyle()
	}

	fun setStyle(s: CaptionStyle)
	{
		style = s
		applyStyle()
		val t = lastText
		if(t != null && box.visibility == View.VISIBLE)
			show(t, lastRect)
	}

	private fun scale(): Float = max(height, resources.displayMetrics.heightPixels).toFloat() / 1080f

	private fun applyStyle()
	{
		val s = scale()
		box.setTextColor(style.fg)
		box.setTextSize(TypedValue.COMPLEX_UNIT_PX, style.size * s)
		val family = when(style.font)
		{
			"serif" -> "serif"
			"condensed" -> "sans-serif-condensed"
			else -> "sans-serif"
		}
		box.typeface = Typeface.create(family, if(style.bold) Typeface.BOLD else Typeface.NORMAL)
		val alpha = (style.bgAlpha * 255).roundToInt().coerceIn(0, 255)
		box.background = GradientDrawable().apply {
			cornerRadius = style.radius * s
			setColor(Color.argb(alpha, Color.red(style.bg), Color.green(style.bg), Color.blue(style.bg)))
		}
		if(style.outline || style.bgAlpha < 0.5f)
			box.setShadowLayer(4f * s, 0f, 1.5f * s, Color.BLACK)
		else
			box.setShadowLayer(0f, 0f, 0f, 0)
		val padH = (22 * s).roundToInt()
		val padV = (10 * s).roundToInt()
		box.setPadding(padH, padV, padH, padV)
	}

	/** [rect] is where the game's own subtitle is, normalised to the screen; null = bottom band. */
	fun show(text: String, rect: NRect?)
	{
		lastText = text
		lastRect = rect
		val w = if(width > 0) width else resources.displayMetrics.widthPixels
		val h = if(height > 0) height else resources.displayMetrics.heightPixels
		if(w == 0 || h == 0)
			return
		applyStyle()
		box.text = text
		val lp = box.layoutParams as LayoutParams
		val maxW = (w * style.maxWidth).roundToInt()
		val margin = (w * 0.03f).roundToInt()

		if(style.placement == "bottom" || rect == null)
		{
			box.minWidth = 0
			box.minHeight = 0
			box.maxWidth = maxW
			lp.gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
			lp.leftMargin = 0
			lp.bottomMargin = (h * style.bottomMargin).roundToInt()
		}
		else
		{
			val pad = (h * 0.012f)
			val boxW = min(maxW, max((w * 0.3f).roundToInt(), (rect.w * w + pad * 2).roundToInt()))
			box.minWidth = boxW
			box.maxWidth = boxW
			// Cover the original lines completely so no English shows through.
			box.minHeight = (rect.h * h + pad * 2).roundToInt()
			val left = (rect.centerX * w - boxW / 2f).roundToInt().coerceIn(margin, max(margin, w - margin - boxW))
			lp.gravity = Gravity.BOTTOM or Gravity.START
			lp.leftMargin = left
			// Grow upwards from the original's bottom edge so long Arabic never leaves the screen.
			lp.bottomMargin = max((h * 0.01f).roundToInt(), (h - (rect.bottom * h + pad)).roundToInt())
		}
		box.layoutParams = lp
		if(box.visibility != View.VISIBLE)
		{
			box.alpha = 0f
			box.visibility = View.VISIBLE
			box.animate().alpha(1f).setDuration(110).start()
		}
	}

	fun hide()
	{
		lastText = null
		if(box.visibility != View.VISIBLE)
			return
		box.animate().cancel()
		box.animate().alpha(0f).setDuration(140).withEndAction { box.visibility = View.GONE }.start()
	}
}
