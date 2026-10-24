package app.countersign.bank.ui.overlay

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.countersign.bank.R
import app.countersign.bank.data.FakeRepository
import app.countersign.bank.data.PayGuardUi
import app.countersign.bank.data.Scenario
import app.countersign.bank.ui.ButtonHeight
import app.countersign.bank.ui.CsTheme

// Darker than the verdict red, for a whole screen of it: white text on it is 7.9:1.
private val GuardRed = Color(0xFF9F1D17)

/**
 * The red screen C shows over a payment app while a scam call is on.
 * "Stop. This caller isn't Rahul." / "Don't send money or share an OTP.", then Ring Rahul, Call Rahul, I understand.
 *
 * State in, lambdas out, and no Activity: C hosts it in an overlay window from a service.
 */
@Composable
fun PayGuardScreen(state: PayGuardUi, onRing: () -> Unit, onCall: () -> Unit, onUnderstood: () -> Unit) {
    val label = state.scam.label
    Column(
        Modifier
            .fillMaxSize()
            .background(GuardRed)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 40.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Icon(Icons.Filled.Warning, contentDescription = null, tint = Color.White, modifier = Modifier.size(72.dp))
        Text(
            stringResource(R.string.guard_title, label),
            Modifier.semantics { heading() },
            color = Color.White,
            style = MaterialTheme.typography.displaySmall,
        )
        Text(
            state.appName?.let { stringResource(R.string.guard_line_app, it) } ?: stringResource(R.string.guard_line),
            color = Color.White,
            style = MaterialTheme.typography.bodyLarge,
        )
        Spacer(Modifier.height(16.dp))
        GuardButton(stringResource(R.string.action_ring_member, label), onRing, filled = true)
        GuardButton(stringResource(R.string.action_call_member, label), onCall, filled = false)
        GuardButton(stringResource(R.string.action_understood), onUnderstood, filled = false)
    }
}

/** Buttons for the red background: white with red words, or outlined in white. */
@Composable
private fun GuardButton(text: String, onClick: () -> Unit, filled: Boolean) {
    val m = Modifier.fillMaxWidth().defaultMinSize(minHeight = ButtonHeight)
    val shape = RoundedCornerShape(14.dp)
    val words: @Composable () -> Unit = { Text(text, style = MaterialTheme.typography.labelLarge, textAlign = TextAlign.Center) }
    if (filled) {
        Button(onClick, m, shape = shape, colors = ButtonDefaults.buttonColors(containerColor = Color.White, contentColor = GuardRed)) { words() }
    } else {
        OutlinedButton(onClick, m, shape = shape, border = BorderStroke(2.dp, Color.White), colors = ButtonDefaults.outlinedButtonColors(contentColor = Color.White)) { words() }
    }
}

private fun guardFor(appName: String?) = PayGuardUi(FakeRepository(Scenario.PAY_GUARD).home.value!!.scam!!, appName)

@Preview(name = "English", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Preview(name = "English, large font", locale = "en", widthDp = 360, heightDp = 800, fontScale = 1.5f)
@Composable
private fun PayGuardPreview() = CsTheme { PayGuardScreen(guardFor("GPay"), {}, {}, {}) }

@Preview(name = "No app name", locale = "hi", widthDp = 360, heightDp = 800)
@Composable
private fun PayGuardNoAppPreview() = CsTheme { PayGuardScreen(guardFor(null), {}, {}, {}) }
