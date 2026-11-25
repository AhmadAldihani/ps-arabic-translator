// Tarjem TV — status and setup screen (works with the TV remote).

package com.tarjem.tv

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

class MainActivity : Activity()
{
	private val handler = Handler(Looper.getMainLooper())
	private lateinit var status: TextView
	private lateinit var address: TextView
	private lateinit var grantButton: Button
	private lateinit var help: TextView
	private val ticker = object : Runnable
	{
		override fun run()
		{
			refresh()
			handler.postDelayed(this, 1000)
		}
	}

	override fun onCreate(savedInstanceState: Bundle?)
	{
		super.onCreate(savedInstanceState)
		val pad = dp(28)
		val root = LinearLayout(this).apply {
			orientation = LinearLayout.VERTICAL
			layoutDirection = View.LAYOUT_DIRECTION_RTL
			setBackgroundColor(Color.rgb(16, 22, 38))
			setPadding(pad * 2, pad, pad * 2, pad)
		}
		root.addView(text("ترجم TV", 34f, Color.rgb(245, 184, 65), bold = true))
		root.addView(text("يعرض الترجمة العربية فوق شاشة البلايستيشن. الترجمة نفسها تجي من برنامج «ترجم» على اللابتوب.", 17f, Color.rgb(190, 200, 220)))

		address = text("", 26f, Color.WHITE, bold = true).apply { setPadding(0, dp(18), 0, dp(6)) }
		root.addView(address)
		status = text("", 19f, Color.rgb(220, 230, 245))
		root.addView(status)

		val buttons = LinearLayout(this).apply {
			orientation = LinearLayout.HORIZONTAL
			layoutDirection = View.LAYOUT_DIRECTION_RTL
			setPadding(0, dp(18), 0, dp(12))
		}
		grantButton = button("منح إذن العرض فوق الشاشة") { openOverlaySettings() }
		buttons.addView(grantButton)
		buttons.addView(button("تجربة الترجمة على الشاشة") {
			OverlayService.start(this, OverlayService.ACTION_TEST)
		})
		buttons.addView(button("إعادة تشغيل الخدمة") {
			stopService(Intent(this, OverlayService::class.java))
			handler.postDelayed({ OverlayService.start(this) }, 600)
		})
		root.addView(buttons)

		help = text("", 16f, Color.rgb(170, 180, 200))
		root.addView(help)

		setContentView(ScrollView(this).apply { addView(root) })
		grantButton.requestFocus()
	}

	override fun onResume()
	{
		super.onResume()
		OverlayService.start(this)
		handler.post(ticker)
	}

	override fun onPause()
	{
		super.onPause()
		handler.removeCallbacks(ticker)
	}

	private fun refresh()
	{
		val canDraw = OverlayService.canDraw(this)
		if(canDraw && !TvState.overlayAttached && TvState.serviceRunning)
			OverlayService.start(this) // permission was just granted: attach the window now
		val ips = NetInfo.localAddresses()
		address.text = if(ips.isEmpty()) "التلفزيون مو متصل بالشبكة"
			else "عنوان التلفزيون: " + ips.joinToString("  أو  ")

		val clients = TvState.clients
		status.text = buildString {
			append(if(canDraw) "✅ إذن العرض فوق الشاشة: مفعّل" else "❌ إذن العرض فوق الشاشة: غير مفعّل (اضغط الزر تحت)")
			append('\n')
			append(if(TvState.serviceRunning) "✅ الخدمة شغّالة (المنفذ ${TvState.port})" else "⏳ الخدمة ما اشتغلت للحين")
			append('\n')
			append(if(clients.isEmpty()) "⏳ ينتظر اتصال برنامج «ترجم» من اللابتوب"
				else "✅ متصل باللابتوب: " + clients.joinToString("، "))
			val last = TvState.lastCaption
			if(last != null && System.currentTimeMillis() - TvState.lastCaptionAt < 60_000)
				append("\n\nآخر ترجمة: ").append(last.replace('\n', ' ').take(80))
			TvState.lastError?.let { append("\n\n⚠️ ").append(it) }
		}
		grantButton.visibility = if(canDraw) View.GONE else View.VISIBLE

		help.text = if(canDraw)
			"الخطوات: ١) شغّل برنامج «ترجم» على اللابتوب واضغط «البحث عن التلفزيون».  ٢) حوّل التلفزيون لمدخل HDMI حق البلايستيشن.  ٣) العب عادي، والترجمة بتطلع فوق اللعبة.\n\nالبرنامج يكمل شغّال في الخلفية، ما تحتاج تخليه مفتوح."
		else
			"إذا ما فتحت صفحة الإذن أو ما لقيت البرنامج فيها: بعض التلفزيونات تخفي هذا الإذن. برنامج «ترجم» على اللابتوب يقدر يفعّله لك من زر «تفعيل الإذن على التلفزيون»، أو بهذا الأمر:\nadb shell appops set com.tarjem.tv SYSTEM_ALERT_WINDOW allow"
	}

	private fun openOverlaySettings()
	{
		val tries = listOf(
			Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")),
			Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION),
			Intent("android.settings.MANAGE_SPECIAL_ACCESS"),
			Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))
		)
		for(i in tries)
		{
			try
			{
				startActivity(i)
				return
			}
			catch(_: ActivityNotFoundException) { }
			catch(_: SecurityException) { }
		}
		help.text = "هذا التلفزيون ما فيه صفحة للإذن. استخدم زر «تفعيل الإذن على التلفزيون» في برنامج اللابتوب."
	}

	private fun text(s: String, size: Float, color: Int, bold: Boolean = false) = TextView(this).apply {
		text = s
		textSize = size
		setTextColor(color)
		textDirection = View.TEXT_DIRECTION_ANY_RTL
		gravity = Gravity.START
		if(bold) typeface = Typeface.DEFAULT_BOLD
		setLineSpacing(0f, 1.2f)
	}

	private fun button(label: String, onClick: () -> Unit) = Button(this).apply {
		text = label
		textSize = 18f
		isAllCaps = false
		setTextColor(Color.WHITE)
		isFocusable = true
		background = GradientDrawable().apply {
			cornerRadius = dp(10).toFloat()
			setColor(Color.rgb(40, 60, 110))
			setStroke(dp(2), Color.rgb(245, 184, 65))
		}
		setPadding(dp(20), dp(10), dp(20), dp(10))
		setOnFocusChangeListener { v, has ->
			(v.background as GradientDrawable).setColor(if(has) Color.rgb(70, 100, 170) else Color.rgb(40, 60, 110))
		}
		setOnClickListener { onClick() }
		layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
			marginEnd = dp(14)
		}
	}

	private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()
}

class BootReceiver : BroadcastReceiver()
{
	override fun onReceive(context: Context, intent: Intent?)
	{
		if(OverlayService.canDraw(context))
			OverlayService.start(context)
	}
}
