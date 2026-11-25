// Tarjemni TV — updates itself from the latest GitHub release (no need to uninstall/reinstall).
// Android always asks the person to confirm an app update; we bring that prompt up for them.

package com.tarjem.tv

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.util.Log
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

object Updater
{
	private const val TAG = "TarjemniUpdate"
	private const val BASE = "https://github.com/AhmadAldihani/ps-arabic-translator/releases/latest/download"

	@Volatile var latest: Long = 0
	/** idle | checking | up_to_date | downloading | ready | installing | error */
	@Volatile var status: String = "idle"
	@Volatile var error: String? = null
	@Volatile private var lastCheck = 0L

	fun current(context: Context): Long = try
	{
		val pi = context.packageManager.getPackageInfo(context.packageName, 0)
		if(Build.VERSION.SDK_INT >= 28) pi.longVersionCode else @Suppress("DEPRECATION") pi.versionCode.toLong()
	}
	catch(e: Exception) { 0L }

	private fun apk(context: Context) = File(context.cacheDir, "update.apk")

	/** Checks (at most every 30 min unless [force]) and downloads a newer APK in the background. */
	fun checkAsync(context: Context, force: Boolean = false, onReady: (() -> Unit)? = null)
	{
		val app = context.applicationContext
		if(!force && System.currentTimeMillis() - lastCheck < 30 * 60_000L)
			return
		if(status == "checking" || status == "downloading")
			return
		lastCheck = System.currentTimeMillis()
		Thread({
			try
			{
				status = "checking"
				val json = JSONObject(get("$BASE/version.json").toString(Charsets.UTF_8))
				latest = json.optLong("tv", 0)
				if(latest <= current(app))
				{
					status = "up_to_date"
					return@Thread
				}
				status = "downloading"
				val bytes = get("$BASE/tarjemni-tv.apk")
				apk(app).writeBytes(bytes)
				status = "ready"
				error = null
				onReady?.invoke()
			}
			catch(e: Exception)
			{
				Log.w(TAG, "update check failed", e)
				status = "error"
				error = e.message
			}
		}, "tarjemni-update").apply { isDaemon = true }.start()
	}

	private fun get(url: String): ByteArray
	{
		var u = URL(url)
		repeat(5) {
			val c = u.openConnection() as HttpURLConnection
			c.connectTimeout = 15_000
			c.readTimeout = 60_000
			c.instanceFollowRedirects = false
			c.setRequestProperty("User-Agent", "Tarjemni-TV")
			val code = c.responseCode
			if(code in 300..399)
			{
				u = URL(u, c.getHeaderField("Location"))
				c.disconnect()
				return@repeat
			}
			if(code != 200)
				throw IllegalStateException("HTTP $code")
			return c.inputStream.use { it.readBytes() }
		}
		throw IllegalStateException("too many redirects")
	}

	/** Starts Android's "update this app?" prompt. Returns false if we first need the install permission. */
	fun install(context: Context): Boolean
	{
		val file = apk(context)
		if(status != "ready" || !file.exists())
			return false
		if(!context.packageManager.canRequestPackageInstalls())
		{
			val i = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
				.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
			try { context.startActivity(i) } catch(_: Exception) { }
			return false
		}
		pauseOverlay(context)
		status = "installing"
		val installer = context.packageManager.packageInstaller
		val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
		params.setAppPackageName(context.packageName)
		val id = installer.createSession(params)
		installer.openSession(id).use { session ->
			file.inputStream().use { input ->
				session.openWrite("tarjemni", 0, file.length()).use { out ->
					input.copyTo(out)
					session.fsync(out)
				}
			}
			val flags = PendingIntent.FLAG_UPDATE_CURRENT or (if(Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0)
			val pi = PendingIntent.getBroadcast(context, id, Intent(context, InstallReceiver::class.java), flags)
			session.commit(pi.intentSender)
		}
		return true
	}

	/** Take the caption layer off the screen for a while, or Android blocks the Update button. */
	fun pauseOverlay(context: Context)
	{
		TvState.overlayPausedUntil = System.currentTimeMillis() + 120_000
		OverlayService.start(context, OverlayService.ACTION_HIDE)
	}
}

class InstallReceiver : BroadcastReceiver()
{
	override fun onReceive(context: Context, intent: Intent)
	{
		when(intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE))
		{
			PackageInstaller.STATUS_PENDING_USER_ACTION -> {
				@Suppress("DEPRECATION")
				val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
				confirm?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
				Updater.pauseOverlay(context)
				try { context.startActivity(confirm) } catch(_: Exception) { }
			}
			PackageInstaller.STATUS_SUCCESS -> Updater.status = "up_to_date"
			else -> {
				TvState.overlayPausedUntil = 0L
				Updater.status = "error"
				Updater.error = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)
			}
		}
	}
}
