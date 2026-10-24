package app.countersign.bank.ui

import android.app.Activity
import android.app.LocaleManager
import android.content.Context
import android.content.res.Configuration
import android.os.Build
import android.os.LocaleList
import app.countersign.bank.data.Lang
import java.util.Locale

/**
 * The app's language, English or Hindi, chosen in the app rather than in phone settings.
 *
 * Android 13+ keeps a per-app language itself and applies it to every activity, service, notification and overlay.
 * On Android 12 the app saves it, and each Activity applies it by calling [wrap] from attachBaseContext; anything else
 * that shows text (a service's overlay window) should build its views from `Language.wrap(context)` too.
 *
 * This only changes what the phone shows. Screens also save it to the account with `repo.setPrefs(lang = …)`.
 */
object Language {
    private const val KEY = "language"

    /** What the person picked, else the phone's language if it's Hindi, else English. */
    fun current(context: Context): Lang {
        val tag = if (Build.VERSION.SDK_INT >= 33) {
            context.getSystemService(LocaleManager::class.java)?.applicationLocales?.get(0)?.language
        } else {
            prefs(context).getString(KEY, null)
        } ?: Locale.getDefault().language
        return if (tag == Lang.HI.code) Lang.HI else Lang.EN
    }

    /** Whether the person has picked a language yet (onboarding asks first if not). */
    fun chosen(context: Context): Boolean = if (Build.VERSION.SDK_INT >= 33) {
        context.getSystemService(LocaleManager::class.java)?.applicationLocales?.isEmpty == false
    } else {
        prefs(context).contains(KEY)
    }

    /** Switch language. The open screens redraw in it straight away. */
    fun set(activity: Activity, lang: Lang) {
        if (Build.VERSION.SDK_INT >= 33) {
            // the system saves it and recreates our activities
            activity.getSystemService(LocaleManager::class.java).applicationLocales = LocaleList.forLanguageTags(lang.code)
        } else {
            prefs(activity).edit().putString(KEY, lang.code).apply()
            activity.recreate()
        }
    }

    /** A context in the chosen language, for Android 12. On 13+ the system already did this, so it's [base] itself. */
    fun wrap(base: Context): Context {
        if (Build.VERSION.SDK_INT >= 33) return base
        val tag = prefs(base).getString(KEY, null) ?: return base
        val config = Configuration(base.resources.configuration).apply { setLocale(Locale.forLanguageTag(tag)) }
        return base.createConfigurationContext(config)
    }

    // the same file as Prefs, opened here so this works from any context without Prefs.init
    private fun prefs(c: Context) = c.getSharedPreferences("csbank", Context.MODE_PRIVATE)
}
