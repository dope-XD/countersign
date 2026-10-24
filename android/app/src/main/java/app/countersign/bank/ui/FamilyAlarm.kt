package app.countersign.bank.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.countersign.bank.R
import app.countersign.bank.data.FalseAlarmReason
import app.countersign.bank.data.FamilyAlarmUi
import app.countersign.bank.data.ScamType
import app.countersign.bank.ui.components.BigButton
import app.countersign.bank.ui.components.ButtonKind
import app.countersign.bank.ui.components.FaceCircle
import app.countersign.bank.ui.components.ago

/**
 * The full-screen alarm on a family member's phone: "Mummy may be on a scam call", the scam in plain words, then
 * Call Mummy (big, green), Message Mummy (with the "cut that call" text shown), OK.
 * [FamilyAlarmUi.cleared] set: Mummy said it was a false alarm, so only the good news and OK.
 * C's FamilyAlarmActivity hosts it over the lock screen and rings.
 */
@Composable
fun FamilyAlarmScreen(state: FamilyAlarmUi, onCall: () -> Unit, onMessage: () -> Unit, onDismiss: () -> Unit) {
    val haptics = LocalHapticFeedback.current
    LaunchedEffect(state.at, state.cleared) { if (state.cleared == null) haptics.performHapticFeedback(HapticFeedbackType.LongPress) }
    val cleared = state.cleared != null
    Column(
        Modifier
            .fillMaxSize()
            .background(if (cleared) GreenSoft else RedSoft)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 40.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        FaceCircle(state.label, key = state.memberId, size = 112.dp)
        Icon(
            if (cleared) Icons.Filled.CheckCircle else Icons.Filled.Warning,
            contentDescription = stringResource(if (cleared) R.string.cd_safe else R.string.cd_danger),
            tint = if (cleared) Green else Red,
            modifier = Modifier.padding(top = 4.dp),
        )
        Text(
            if (cleared) stringResource(R.string.alarm_cleared_title, state.label) else stringResource(R.string.alarm_title, state.label),
            Modifier.semantics { heading() },
            color = if (cleared) Green else Red,
            style = MaterialTheme.typography.headlineLarge,
            textAlign = TextAlign.Center,
        )
        Text(
            if (cleared) stringResource(R.string.alarm_cleared_body, state.label) else stringResource(alarmLine(state.type)),
            color = Ink,
            style = MaterialTheme.typography.bodyLarge,
            textAlign = TextAlign.Center,
        )
        Text(ago(state.at), color = Muted, style = MaterialTheme.typography.bodyMedium)
        Spacer(Modifier.height(16.dp))
        if (!cleared) {
            BigButton(stringResource(R.string.action_call_member, state.label), onCall, kind = ButtonKind.Yes, icon = Icons.Filled.Call)
            BigButton(stringResource(R.string.alarm_message_member, state.label), onMessage, kind = ButtonKind.Quiet, icon = Icons.Filled.Email)
            Text(
                stringResource(R.string.alarm_will_send, stringResource(R.string.alarm_message, state.label)),
                color = Muted,
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
            )
        }
        BigButton(stringResource(R.string.action_ok), onDismiss, kind = ButtonKind.Quiet)
    }
}

/** One line per scam type, in plain words. */
fun alarmLine(t: ScamType): Int = when (t) {
    ScamType.DIGITAL_ARREST -> R.string.alarm_digital_arrest
    ScamType.BANK_KYC -> R.string.alarm_bank_kyc
    ScamType.OTP_UPI -> R.string.alarm_otp_upi
    ScamType.REMOTE_ACCESS -> R.string.alarm_remote_access
    ScamType.FAMILY_EMERGENCY -> R.string.alarm_family_emergency
    ScamType.COURIER_CUSTOMS -> R.string.alarm_courier_customs
    ScamType.TRAI_SIM -> R.string.alarm_trai_sim
    ScamType.JOB_TASK -> R.string.alarm_job_task
    ScamType.INVESTMENT -> R.string.alarm_investment
    ScamType.REWARD -> R.string.alarm_reward
    ScamType.IMPERSONATION -> R.string.alarm_impersonation
    ScamType.UNKNOWN -> R.string.alarm_unknown
}

private val alarm = FamilyAlarmUi("c_papa", "Papa", ScamType.DIGITAL_ARREST, System.currentTimeMillis() - 60_000)

@Preview(name = "English", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Preview(name = "English, large font", locale = "en", widthDp = 360, heightDp = 800, fontScale = 1.5f)
@Composable
private fun FamilyAlarmPreview() = CsTheme { FamilyAlarmScreen(alarm, {}, {}, {}) }

@Preview(name = "Cleared, English", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Cleared, Hindi", locale = "hi", widthDp = 360, heightDp = 800, fontScale = 1.5f)
@Composable
private fun FamilyAlarmClearedPreview() = CsTheme { FamilyAlarmScreen(alarm.copy(cleared = FalseAlarmReason.KNOW_CALLER), {}, {}, {}) }
