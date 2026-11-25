// Tarjemni TV — bundled Arabic fonts (SIL Open Font License, see assets/fonts/OFL-*.txt).

package com.tarjem.tv

import android.content.Context
import android.graphics.Typeface

object Fonts
{
	private val cache = HashMap<String, Typeface>()

	/** [id]: cairo | tajawal | plex | naskh | system. Variable fonts get the right weight via 'wght'. */
	fun get(context: Context, id: String, bold: Boolean): Typeface = synchronized(cache) {
		val key = "$id/$bold"
		cache[key]?.let { return it }
		val tf = try
		{
			when(id)
			{
				"cairo" -> variable(context, "fonts/cairo.ttf", if(bold) 700 else 500)
				"naskh" -> variable(context, "fonts/naskh.ttf", if(bold) 700 else 500)
				"tajawal" -> Typeface.createFromAsset(context.assets, if(bold) "fonts/tajawal-bold.ttf" else "fonts/tajawal-regular.ttf")
				"plex" -> Typeface.createFromAsset(context.assets, if(bold) "fonts/plex-bold.ttf" else "fonts/plex-regular.ttf")
				"serif" -> Typeface.create("serif", if(bold) Typeface.BOLD else Typeface.NORMAL)
				"condensed" -> Typeface.create("sans-serif-condensed", if(bold) Typeface.BOLD else Typeface.NORMAL)
				else -> Typeface.create(Typeface.SANS_SERIF, if(bold) Typeface.BOLD else Typeface.NORMAL)
			}
		}
		catch(e: Exception)
		{
			Typeface.create(Typeface.SANS_SERIF, if(bold) Typeface.BOLD else Typeface.NORMAL)
		}
		cache[key] = tf
		tf
	}

	private fun variable(context: Context, path: String, weight: Int): Typeface =
		Typeface.Builder(context.assets, path)
			.setFontVariationSettings("'wght' $weight")
			.setWeight(weight)
			.build() ?: Typeface.createFromAsset(context.assets, path)
}
