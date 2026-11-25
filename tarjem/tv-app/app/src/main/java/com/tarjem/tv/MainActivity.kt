// Tarjemni TV — status and setup screen (works with the TV remote).

package com.tarjem.tv

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

class MainActivity : Activity()
{
	private val handler = Handler(Looper.getMainLooper())
	private lateinit var address: TextView
	private lateinit var rows: LinearLayout
	private lateinit var grantButton: Button
	private lateinit var updateCard: LinearLayout
	private lateinit var updateText: TextView
	private lateinit var help: TextView
	private var askedInstall = false
	private val ticker = object : Runnable
	{
		override fun run()
		{
			refresh()
			handler.postDelayed(this, 1000)
		}
	}

	private val pink = Color.rgb(255, 79, 160)
	private val violet = Color.rgb(123, 92, 255)
	private val muted = Color.rgb(150, 158, 180)

	override fun onCreate(savedInstanceState: Bundle?)
	{
		super.onCreate(savedInstanceState)
		val pad = dp(36)
		val root = LinearLayout(this).apply {
			orientation = LinearLayout.VERTICAL
			layoutDirection = View.LAYOUT_DIRECTION_RTL
			setPadding(pad * 2, pad, pad * 2, pad)
		}

		// header
		val header = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
		header.addView(TextView(this).apply {
			text = "ت"
			textSize = 30f
			gravity = Gravity.CENTER
			setTextColor(Color.WHITE)
			typeface = Fonts.get(context, "cairo", true)
			background = GradientDrawable(GradientDrawable.Orientation.TL_BR, intArrayOf(pink, violet)).apply { cornerRadius = dp(18).toFloat() }
		}, LinearLayout.LayoutParams(dp(64), dp(64)))
		val titles = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(18), 0, dp(18), 0) }
		titles.addView(text("ترجمني", 34f, Color.WHITE, bold = true, font = "cairo"))
		titles.addView(text("ترجمة عربية فوق ألعاب بلايستيشن · الإصدار ${Updater.current(this)}", 15f, muted))
		header.addView(titles)
		root.addView(header)

		// update banner
		updateCard = card(Color.argb(60, 123, 92, 255)).apply { visibility = View.GONE }
		updateText = text("", 18f, Color.WHITE, bold = true)
		updateCard.addView(updateText)
		updateCard.addView(button("تثبيت التحديث الآن", primary = true) { askedInstall = true; Updater.install(this) })
		root.addView(updateCard, spaced())

		// address card
		val addrCard = card(Color.argb(160, 22, 26, 40))
		addrCard.addView(text("عنوان التلفزيون (اكتبه في برنامج اللابتوب إذا ما لقاه)", 15f, muted))
		address = text("", 30f, Color.WHITE, bold = true).apply { textDirection = View.TEXT_DIRECTION_LTR; gravity = Gravity.END }
		addrCard.addView(address)
		root.addView(addrCard, spaced())

		// status rows
		rows = card(Color.argb(160, 22, 26, 40))
		root.addView(rows, spaced())

		// buttons
		val buttons = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(0, dp(16), 0, dp(8)) }
		grantButton = button("منح إذن العرض فوق الشاشة", primary = true) { openOverlaySettings() }
		buttons.addView(grantButton)
		buttons.addView(button("تجربة الترجمة على الشاشة", primary = false) { OverlayService.start(this, OverlayService.ACTION_TEST) })
		buttons.addView(button("البحث عن تحديث", primary = false) { Updater.checkAsync(this, force = true) })
		root.addView(buttons)

		help = text("", 15f, muted)
		root.addView(help, spaced())

		val bg = FrameLayout(this).apply {
			background = GradientDrawable(GradientDrawable.Orientation.TL_BR,
				intArrayOf(Color.rgb(32, 18, 52), Color.rgb(9, 11, 20), Color.rgb(8, 10, 18)))
		}
		bg.addView(ScrollView(this).apply { addView(root) })
		setContentView(bg)
		grantButton.requestFocus()
	}

	override fun onResume()
	{
		super.onResume()
		OverlayService.start(this)
		Updater.checkAsync(this)
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
			OverlayService.start(this)
		val ips = NetInfo.localAddresses()
		address.text = if(ips.isEmpty()) "غير متصل بالشبكة" else ips.joinToString("   ")

		val clients = TvState.clients
		rows.removeAllViews()
		rows.addView(status(canDraw, if(canDraw) "إذن العرض فوق الشاشة مفعّل" else "إذن العرض فوق الشاشة غير مفعّل — اضغط الزر تحت"))
		rows.addView(status(TvState.serviceRunning, if(TvState.serviceRunning) "الخدمة شغّالة في الخلفية" else "الخدمة ما اشتغلت للحين"))
		rows.addView(status(clients.isNotEmpty(), if(clients.isEmpty()) "ينتظر برنامج «ترجمني» من اللابتوب" else "متصل باللابتوب: " + clients.joinToString("، ")))
		val last = TvState.lastCaption
		if(last != null && System.currentTimeMillis() - TvState.lastCaptionAt < 60_000)
			rows.addView(text("آخر ترجمة: " + last.take(90), 15f, muted))
		TvState.lastError?.let { rows.addView(text("⚠ $it", 14f, Color.rgb(255, 120, 130))) }
		grantButton.visibility = if(canDraw) View.GONE else View.VISIBLE

		when(Updater.status)
		{
			"downloading" -> { updateCard.visibility = View.VISIBLE; updateText.text = "⬇ جاري تنزيل التحديث ${Updater.latest}…" }
			"ready" -> {
				updateCard.visibility = View.VISIBLE
				updateText.text = "✨ تحديث جديد جاهز (الإصدار ${Updater.latest}). اضغط «تحديث» في الرسالة اللي تطلع."
				if(!askedInstall) { askedInstall = true; Updater.install(this) }
			}
			else -> updateCard.visibility = View.GONE
		}

		help.text = if(canDraw)
			"الخطوات: ١) شغّل «ترجمني» على اللابتوب واضغط «ابحث عن التلفزيون».  ٢) حوّل التلفزيون لمدخل HDMI حق البلايستيشن.  ٣) العب عادي، والترجمة تطلع فوق اللعبة.\nالبرنامج يشتغل في الخلفية ويتحدّث لحاله."
		else
			"إذا ما لقيت الإذن في التلفزيون: برنامج اللابتوب يقدر يفعّله من «التلفزيون متصل بس ما يعرض شي»، أو بالأمر:\nadb shell appops set com.tarjem.tv SYSTEM_ALERT_WINDOW allow"
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
		help.text = "هذا التلفزيون ما فيه صفحة للإذن. استخدم «تفعيل الإذن على التلفزيون» في برنامج اللابتوب."
	}

	// ---- small UI helpers --------------------------------------------------------

	private fun text(s: String, size: Float, color: Int, bold: Boolean = false, font: String = "plex") = TextView(this).apply {
		text = s
		textSize = size
		setTextColor(color)
		textDirection = View.TEXT_DIRECTION_ANY_RTL
		gravity = Gravity.START
		typeface = Fonts.get(context, font, bold)
		setLineSpacing(0f, 1.25f)
	}

	private fun status(ok: Boolean, label: String) = LinearLayout(this).apply {
		orientation = LinearLayout.HORIZONTAL
		gravity = Gravity.CENTER_VERTICAL
		setPadding(0, dp(6), 0, dp(6))
		addView(View(context).apply {
			background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(if(ok) Color.rgb(47, 212, 138) else Color.rgb(255, 181, 71)) }
		}, LinearLayout.LayoutParams(dp(12), dp(12)).apply { marginEnd = dp(12) })
		addView(text(label, 19f, Color.WHITE))
	}

	private fun card(color: Int) = LinearLayout(this).apply {
		orientation = LinearLayout.VERTICAL
		setPadding(dp(24), dp(18), dp(24), dp(18))
		background = GradientDrawable().apply {
			cornerRadius = dp(20).toFloat()
			setColor(color)
			setStroke(dp(1), Color.argb(30, 255, 255, 255))
		}
	}

	private fun spaced() = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
		topMargin = dp(16)
	}

	private fun button(label: String, primary: Boolean, onClick: () -> Unit) = Button(this).apply {
		text = label
		textSize = 18f
		isAllCaps = false
		typeface = Fonts.get(context, "plex", true)
		setTextColor(Color.WHITE)
		isFocusable = true
		val normal = if(primary) GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT, intArrayOf(pink, violet))
			else GradientDrawable().apply { setColor(Color.argb(40, 255, 255, 255)) }
		normal.cornerRadius = dp(14).toFloat()
		background = normal
		setPadding(dp(24), dp(12), dp(24), dp(12))
		setOnFocusChangeListener { v, has ->
			(v.background as GradientDrawable).setStroke(if(has) dp(3) else 0, Color.WHITE)
			v.scaleX = if(has) 1.05f else 1f
			v.scaleY = if(has) 1.05f else 1f
		}
		setOnClickListener { onClick() }
		layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
			marginEnd = dp(16)
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
