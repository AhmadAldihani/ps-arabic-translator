// Tarjem TV — keeps the overlay window and the LAN server alive while you play.

package com.tarjem.tv

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.PixelFormat
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.provider.Settings
import android.util.Log
import android.view.Gravity
import android.view.WindowManager

/** Read by the status screen. */
object TvState
{
	@Volatile var serviceRunning = false
	@Volatile var overlayAttached = false
	@Volatile var port = SERVER_PORT
	@Volatile var clients: List<String> = emptyList()
	@Volatile var lastCaption: String? = null
	@Volatile var lastCaptionAt = 0L
	@Volatile var lastError: String? = null
}

class OverlayService : Service()
{
	companion object
	{
		private const val TAG = "TarjemOverlay"
		private const val CHANNEL = "tarjem"
		const val ACTION_TEST = "com.tarjem.tv.TEST"
		private const val TEST_TEXT = "هذي تجربة للترجمة العربية ✓\nإذا تشوف هالمربع فوق اللعبة، كل شي تمام"

		fun start(context: Context, action: String? = null)
		{
			val i = Intent(context, OverlayService::class.java)
			if(action != null)
				i.action = action
			try
			{
				context.startForegroundService(i)
			}
			catch(e: Exception)
			{
				TvState.lastError = "start: $e"
			}
		}

		fun canDraw(context: Context) = Settings.canDrawOverlays(context)
	}

	private val main = Handler(Looper.getMainLooper())
	private var layer: CaptionLayer? = null
	private var style = CaptionStyle()
	private var multicastLock: WifiManager.MulticastLock? = null
	private val hideRunnable = Runnable { layer?.hide() }

	private val server = NetServer(
		onMessage = { client, msg -> main.post { handle(client, msg) } },
		onClientsChanged = { list -> TvState.clients = list.map { it.name } }
	)

	override fun onBind(intent: Intent?): IBinder? = null

	override fun onCreate()
	{
		super.onCreate()
		startInForeground()
		try
		{
			val wifi = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
			multicastLock = wifi.createMulticastLock("tarjem").apply { setReferenceCounted(false); acquire() }
		}
		catch(e: Exception)
		{
			Log.w(TAG, "no multicast lock: $e")
		}
		server.describe = {
			Protocol.reply("tv", mapOf(
				"name" to (Settings.Global.getString(contentResolver, "device_name") ?: Build.MODEL),
				"port" to server.port,
				"overlay" to TvState.overlayAttached,
				"version" to 1))
		}
		server.start()
		TvState.serviceRunning = true
		attachOverlay()
	}

	override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int
	{
		if(!TvState.overlayAttached)
			attachOverlay()
		TvState.port = server.port
		if(intent?.action == ACTION_TEST)
			showCaption(TEST_TEXT, null, 6000)
		return START_STICKY
	}

	override fun onDestroy()
	{
		server.stop()
		main.removeCallbacksAndMessages(null)
		detachOverlay()
		try { multicastLock?.release() } catch(_: Exception) { }
		TvState.serviceRunning = false
		super.onDestroy()
	}

	private fun startInForeground()
	{
		val nm = getSystemService(NotificationManager::class.java)!!
		nm.createNotificationChannel(NotificationChannel(CHANNEL, "ترجم", NotificationManager.IMPORTANCE_LOW))
		val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
			PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
		val n = Notification.Builder(this, CHANNEL)
			.setSmallIcon(R.drawable.ic_app)
			.setContentTitle("ترجم TV شغّال")
			.setContentText("ينتظر الترجمة من اللابتوب")
			.setContentIntent(open)
			.setOngoing(true)
			.build()
		startForeground(1, n)
	}

	private fun attachOverlay()
	{
		if(layer != null || !canDraw(this))
		{
			TvState.overlayAttached = layer != null
			return
		}
		val wm = getSystemService(WindowManager::class.java)!!
		val lp = WindowManager.LayoutParams(
			WindowManager.LayoutParams.MATCH_PARENT,
			WindowManager.LayoutParams.MATCH_PARENT,
			WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
			// No FLAG_NOT_TOUCHABLE: Android 12+ caps pass-through overlays at 80% opacity,
			// which would let the English subtitle show through. TVs have no touch screen anyway,
			// and NOT_FOCUSABLE keeps every remote/controller key going to the game.
			WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
				WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
				WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
				WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
				WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
			PixelFormat.TRANSLUCENT)
		lp.gravity = Gravity.TOP or Gravity.START
		lp.title = "TarjemCaptions"
		lp.alpha = 1f
		val view = CaptionLayer(this)
		view.setStyle(style)
		try
		{
			wm.addView(view, lp)
			layer = view
			TvState.overlayAttached = true
			TvState.lastError = null
		}
		catch(e: Exception)
		{
			Log.e(TAG, "cannot add overlay", e)
			TvState.overlayAttached = false
			TvState.lastError = "overlay: ${e.message}"
		}
	}

	private fun detachOverlay()
	{
		val v = layer ?: return
		try { getSystemService(WindowManager::class.java)?.removeView(v) } catch(_: Exception) { }
		layer = null
		TvState.overlayAttached = false
	}

	private fun handle(client: Client, msg: Msg)
	{
		when(msg)
		{
			is Msg.Hello -> {
				if(layer == null)
					attachOverlay()
				val dm = resources.displayMetrics
				client.send(Protocol.reply("welcome", mapOf(
					"name" to (Settings.Global.getString(contentResolver, "device_name") ?: Build.MODEL),
					"overlay" to TvState.overlayAttached,
					"w" to dm.widthPixels, "h" to dm.heightPixels, "version" to 1)))
			}
			is Msg.Show -> showCaption(msg.text, msg.rect, msg.ttlMs)
			is Msg.Keep -> {
				main.removeCallbacks(hideRunnable)
				main.postDelayed(hideRunnable, msg.ttlMs)
			}
			Msg.Clear -> {
				main.removeCallbacks(hideRunnable)
				layer?.hide()
			}
			is Msg.Style -> {
				style = style.merge(msg.patch)
				layer?.setStyle(style)
				client.send(Protocol.reply("style_ok"))
			}
			Msg.Ping -> client.send(Protocol.reply("pong", mapOf("overlay" to TvState.overlayAttached)))
			Msg.Test -> showCaption(TEST_TEXT, null, 6000)
		}
	}

	private fun showCaption(text: String, rect: NRect?, ttl: Long)
	{
		if(layer == null)
			attachOverlay()
		val l = layer ?: return
		l.show(text, rect)
		TvState.lastCaption = text
		TvState.lastCaptionAt = System.currentTimeMillis()
		main.removeCallbacks(hideRunnable)
		main.postDelayed(hideRunnable, ttl)
	}
}

