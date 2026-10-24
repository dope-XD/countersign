package app.countersign.bank.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.countersign.bank.ui.CsTheme
import app.countersign.bank.ui.Paper

/** Every UI preview: English, Hindi, and English at the largest common font size, on a 360 dp phone. */
@Preview(name = "English", locale = "en", widthDp = 360, showBackground = true)
@Preview(name = "Hindi", locale = "hi", widthDp = 360, showBackground = true)
@Preview(name = "English, large font", locale = "en", widthDp = 360, fontScale = 1.5f, showBackground = true)
annotation class PreviewLanguages

/** Wraps a preview in the app theme on the app background. */
@Composable
fun PreviewBox(content: @Composable () -> Unit) {
    CsTheme { Column(Modifier.background(Paper).padding(16.dp)) { content() } }
}
