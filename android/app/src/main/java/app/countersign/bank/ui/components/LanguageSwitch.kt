package app.countersign.bank.ui.components

import android.app.Activity
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import app.countersign.bank.R
import app.countersign.bank.data.Lang
import app.countersign.bank.ui.Language

/**
 * Two big buttons, "English" and "हिंदी", each written in its own language so anyone can find theirs.
 * The current one is filled with a tick. Tapping one switches the app; [onPicked] is for saving it to the account
 * (`signUp(…, lang)` in onboarding, `setPrefs(lang = …)` in Settings).
 */
@Composable
fun LanguageSwitch(modifier: Modifier = Modifier, onPicked: (Lang) -> Unit = {}) {
    val context = LocalContext.current
    // what the screen is actually drawn in, which is also right in previews
    val current = if (LocalConfiguration.current.locales[0].language == Lang.HI.code) Lang.HI else Lang.EN
    Column(modifier, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        listOf(Lang.EN to R.string.language_english, Lang.HI to R.string.language_hindi).forEach { (lang, name) ->
            val on = lang == current
            BigButton(
                stringResource(name),
                onClick = {
                    // save it even when it's already showing, so onboarding knows it was picked
                    (context as? Activity)?.let { if (!on || !Language.chosen(it)) Language.set(it, lang) }
                    onPicked(lang)
                },
                kind = if (on) ButtonKind.Primary else ButtonKind.Quiet,
                icon = if (on) Icons.Filled.Check else null,
            )
        }
    }
}

@PreviewLanguages
@Composable
private fun LanguageSwitchPreview() = PreviewBox { LanguageSwitch() }
