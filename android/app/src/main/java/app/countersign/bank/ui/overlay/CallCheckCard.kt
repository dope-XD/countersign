package app.countersign.bank.ui.overlay

import android.annotation.SuppressLint
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Phone
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.tooling.preview.PreviewParameter
import androidx.compose.ui.tooling.preview.PreviewParameterProvider
import androidx.compose.ui.unit.dp
import app.countersign.bank.R
import app.countersign.bank.data.CallCheckUi
import app.countersign.bank.data.Check
import app.countersign.bank.data.FakeRepository
import app.countersign.bank.data.ListenState
import app.countersign.bank.data.Member
import app.countersign.bank.data.Outcome
import app.countersign.bank.data.RingState
import app.countersign.bank.data.RiskLevel
import app.countersign.bank.data.RiskSource
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.material3.TextButton
import app.countersign.bank.ui.components.whyLine
import app.countersign.bank.data.FalseAlarmReason
import app.countersign.bank.data.ScamType
import app.countersign.bank.data.Scenario
import app.countersign.bank.data.Verdict
import app.countersign.bank.ui.Amber
import app.countersign.bank.ui.AmberSoft
import app.countersign.bank.ui.Brand
import app.countersign.bank.ui.CsTheme
import app.countersign.bank.ui.Green
import app.countersign.bank.ui.Grey
import app.countersign.bank.ui.GreySoft
import app.countersign.bank.ui.Ink
import app.countersign.bank.ui.Line
import app.countersign.bank.ui.Muted
import app.countersign.bank.ui.Red
import app.countersign.bank.ui.RedSoft
import app.countersign.bank.ui.components.BigButton
import app.countersign.bank.ui.components.ButtonKind
import app.countersign.bank.ui.components.MemberFace
import app.countersign.bank.ui.components.VerdictChip
import app.countersign.bank.ui.components.familyColours
import kotlinx.coroutines.delay

/**
 * The card C shows over the dialer during a call: is the caller really who they say?
 *
 * State in, lambdas out, and no Activity: C hosts it in an overlay window from a service.
 * - An unknown number: the "Says they're family? Check" chip, then a row of faces; [onPickMember] gets the member id.
 * - A check: its verdict, and on ✗ or ? the Ring / Call buttons. A ✓ fades after 4 s and then calls [onClose].
 * - While a ring is out: "Ringing Rahul…", then what Rahul answered.
 * - The call listener: "Put on speaker so we can listen", a quiet "Listening for scams", an amber card at
 *   `warn` (the scam type, one line of advice, [onAlertFamily]) and a red one at `scam` ("Hang up", "Family
 *   alerted ✓" and a Call button: [onCall] for the checked member, else [onCallMember] with someone online).
 *   Both cards say why they fired (the cue ids in plain words) and offer the false-alarm path: "I know this caller"
 *   on amber, "It's not a scam" on red, each with an inline confirm, then [onNotAScam]. A cleared call shows one
 *   green line, "Cleared. Family told it's fine."
 *
 * It never takes more than the top third of the screen (45% while warning, which still keeps clear of the bottom
 * half), so the dialer's end-call button stays free. If large fonts make it taller than that, it scrolls.
 */
// The screen's height, not the window's: C's overlay window wraps the card, so its own size says nothing.
@SuppressLint("ConfigurationScreenWidthHeight")
@Composable
fun CallCheckCard(
    state: CallCheckUi,
    onRing: () -> Unit,
    onCall: () -> Unit,
    onPickMember: (String) -> Unit,
    onClose: () -> Unit,
    onAlertFamily: () -> Unit = {},
    onCallMember: (String) -> Unit = {},
    onNotAScam: (FalseAlarmReason) -> Unit = {},
) {
    val check = state.check
    val level = state.risk?.level
    val alarmed = level == RiskLevel.WARN || level == RiskLevel.SCAM
    val fades = !alarmed && check != null && check.ring == RingState.NONE && (check.verdict == Verdict.VERIFIED || check.verdict == Verdict.LIKELY)
    var shown by remember(check?.id) { mutableStateOf(true) }
    LaunchedEffect(check?.id, fades) {
        if (fades) {
            delay(4_000)
            shown = false
            delay(FADE_MS.toLong())
            onClose()
        }
    }

    // buzz once when a check turns ✗, and when the listener says scam
    val haptics = LocalHapticFeedback.current
    LaunchedEffect(check?.id, check?.outcome, level == RiskLevel.SCAM) {
        if (check?.outcome == Outcome.DANGER || level == RiskLevel.SCAM) haptics.performHapticFeedback(HapticFeedbackType.LongPress)
    }

    val maxHeight = (LocalConfiguration.current.screenHeightDp * if (alarmed) 0.45f else 1 / 3f).dp
    AnimatedVisibility(shown, exit = fadeOut(tween(FADE_MS))) {
        Card(
            Modifier.fillMaxWidth().padding(8.dp).heightIn(max = maxHeight),
            shape = RoundedCornerShape(20.dp),
            colors = CardDefaults.cardColors(containerColor = Color.White),
            elevation = CardDefaults.cardElevation(defaultElevation = 8.dp),
        ) {
            Column(
                Modifier.verticalScroll(rememberScrollState()).padding(start = 16.dp, end = 4.dp, top = 4.dp, bottom = 16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                // an unknown caller's "Says they're family?" chip is moot once the listener warns; its card takes the close button
                if (check != null) CheckBody(check, onRing, onCall, onClose, actions = !alarmed) else if (!alarmed) UnknownCaller(state.family, onPickMember, onClose)
                Listener(state, onAlertFamily, onCall, onCallMember, onNotAScam, onClose = if (check == null) onClose else null)
                if (state.listen == ListenState.LISTENING || state.risk != null) Prompter(state)
            }
        }
    }
}

private const val FADE_MS = 300

/** The top line of the card: [content] (a verdict or the family chip) with the close button beside it. */
@Composable
private fun HeaderRow(onClose: () -> Unit, content: @Composable () -> Unit) {
    Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.weight(1f)) { content() }
        IconButton(onClose, Modifier.size(48.dp)) {
            Icon(Icons.Filled.Close, contentDescription = stringResource(R.string.action_close), tint = Grey)
        }
    }
}

@Composable
private fun CheckBody(check: Check, onRing: () -> Unit, onCall: () -> Unit, onClose: () -> Unit, actions: Boolean) {
    val label = check.label
    HeaderRow(onClose) {
        when (check.ring) {
            RingState.RINGING -> VerdictChip(Verdict.CHECKING, label, words = stringResource(R.string.card_ringing, label))
            RingState.YES -> VerdictChip(Verdict.VERIFIED, label, words = stringResource(R.string.card_ring_yes, label))
            RingState.NO -> VerdictChip(Verdict.NOT_THEM, label, words = stringResource(R.string.card_ring_no, label))
            RingState.NO_ANSWER -> VerdictChip(Verdict.CANT_REACH, label, words = stringResource(R.string.card_no_answer, label))
            RingState.NONE -> VerdictChip(check.verdict, label, spoofSuspected = check.spoofSuspected)
        }
    }
    val line = when {
        check.ring == RingState.NO -> stringResource(R.string.card_dont_send_money)
        check.ring != RingState.NONE -> null
        check.verdict == Verdict.NOT_WITH_YOU -> stringResource(R.string.card_line_not_with_you, label)
        check.verdict == Verdict.NOT_THEM -> stringResource(R.string.card_line_not_them, label)
        check.verdict == Verdict.CANT_REACH -> stringResource(R.string.card_line_cant_reach, label)
        else -> null
    }
    // while the listener's warn or scam card is up, it carries the advice and the buttons
    if (!actions) return
    if (line != null) Text(line, Modifier.padding(end = 12.dp), color = Ink, style = MaterialTheme.typography.bodyMedium)

    // Ring and Call while it's ✗ or ?; Call alone once a ring is answered "no" or not at all
    val canRing = check.ring == RingState.NONE && (check.outcome == Outcome.DANGER || check.outcome == Outcome.UNKNOWN)
    val canCall = canRing || check.ring == RingState.NO_ANSWER || check.ring == RingState.NO
    if (canCall) {
        // side by side to stay in the top third, so no icons: the words need the width
        Row(Modifier.padding(end = 12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            if (canRing) BigButton(stringResource(R.string.action_ring_member, label), onRing, Modifier.weight(1f))
            BigButton(
                stringResource(R.string.action_call_member, label), onCall, Modifier.weight(1f),
                kind = if (canRing) ButtonKind.Quiet else ButtonKind.Primary, icon = if (canRing) null else Icons.Filled.Call,
            )
        }
    }
}

/** What the call listener adds under the caller check: the speaker chip, the listening line, or the warn / scam card. */
@Composable
private fun Listener(
    state: CallCheckUi,
    onAlertFamily: () -> Unit,
    onCall: () -> Unit,
    onCallMember: (String) -> Unit,
    onNotAScam: (FalseAlarmReason) -> Unit,
    onClose: (() -> Unit)?,
) {
    val risk = state.risk
    // the false-alarm confirm, inline: an overlay window can't open a dialog
    var confirming by remember(risk?.level) { mutableStateOf<FalseAlarmReason?>(null) }
    val why = risk?.let { whyLine(it.cues) }
    when {
        state.cleared -> Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Icon(Icons.Filled.Check, contentDescription = null, tint = Green, modifier = Modifier.size(24.dp))
            Text(stringResource(R.string.cleared_line), color = Ink, style = MaterialTheme.typography.bodyMedium)
        }
        confirming != null && risk != null -> RiskCard(Grey, GreySoft, stringResource(R.string.not_scam_confirm_title), stringResource(R.string.not_scam_confirm_body), null) {
            Row(Modifier.padding(end = 12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                BigButton(stringResource(R.string.action_yes_its_fine), { onNotAScam(confirming!!) }, Modifier.weight(1f), kind = ButtonKind.Yes)
                BigButton(stringResource(R.string.action_back), { confirming = null }, Modifier.weight(1f), kind = ButtonKind.Quiet)
            }
        }
        risk?.level == RiskLevel.SCAM -> {
            // the checked member's own number, or else someone in the family who's online
            val check = state.check
            val other = state.family.firstOrNull { it.online } ?: state.family.firstOrNull()
            val callLabel = check?.label ?: other?.label
            val call = if (check != null) onCall else other?.let { m -> { onCallMember(m.id) } }
            // no advice line here: "Hang up" is the advice, and the buttons must stay in view
            RiskCard(Red, RedSoft, stringResource(R.string.scam_title), why, onClose) {
                Row(Modifier.padding(end = 12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    // the family is alarmed as soon as a call reaches scam
                    Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Icon(Icons.Filled.Check, contentDescription = null, tint = Green, modifier = Modifier.size(24.dp))
                        // ink, not green: green on this pink is 4.46:1, under the 4.5 minimum
                        Text(stringResource(R.string.family_alerted), color = Ink, style = MaterialTheme.typography.bodyMedium)
                    }
                    if (call != null && callLabel != null) {
                        BigButton(stringResource(R.string.action_call_member, callLabel), call, Modifier.weight(1.3f), icon = Icons.Filled.Call)
                    }
                }
                FalseAlarmLink(stringResource(R.string.action_not_a_scam)) { confirming = FalseAlarmReason.NOT_A_SCAM }
            }
        }
        risk?.level == RiskLevel.WARN ->
            RiskCard(Amber, AmberSoft, stringResource(risk.type.headline()), listOfNotNull(stringResource(risk.type.advice()), why).joinToString("\n"), onClose) {
                BigButton(stringResource(R.string.action_alert_family), onAlertFamily, Modifier.padding(end = 12.dp), kind = ButtonKind.No)
                FalseAlarmLink(stringResource(R.string.action_know_caller)) { confirming = FalseAlarmReason.KNOW_CALLER }
            }
        state.listen == ListenState.NEED_SPEAKER -> Row(
            Modifier.padding(end = 12.dp).border(2.dp, Line, RoundedCornerShape(24.dp)).padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(Icons.Filled.Phone, contentDescription = null, tint = Brand, modifier = Modifier.size(24.dp))
            Text(stringResource(R.string.listen_need_speaker), color = Ink, style = MaterialTheme.typography.bodyMedium)
        }
        state.listen == ListenState.LISTENING -> Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Box(Modifier.size(10.dp).background(Green, CircleShape))
            Text(stringResource(R.string.listen_listening), color = Muted, style = MaterialTheme.typography.bodyMedium)
        }
    }
}

/**
 * The prompter: what Countersign is doing on this call right now, and one thing to watch for, in plain words.
 * While the call looks fine the tip changes every 8 s; once it warns, the card above says what to do.
 */
@Composable
private fun Prompter(state: CallCheckUi) {
    val level = state.risk?.level
    val doing = buildList {
        if (state.cleared) return@buildList
        when {
            // at red the card above already says the family is alerted: say what the server did instead
            level == RiskLevel.SCAM -> if (state.risk?.sources?.contains(RiskSource.SERVER) == true) add(R.string.prompt_doing_server_done)
            state.serverCheck -> add(R.string.prompt_doing_server)
            level == RiskLevel.WARN -> add(R.string.prompt_doing_warn)
            else -> add(R.string.prompt_doing_listening)
        }
        if (state.paymentsPaused) add(R.string.prompt_payments_paused)
    }
    var tip by remember { mutableIntStateOf(0) }
    LaunchedEffect(level) {
        while (level == null || level == RiskLevel.NONE || level == RiskLevel.WATCH) {
            delay(8_000)
            tip = (tip + 1) % TIPS.size
        }
    }
    Column(Modifier.padding(end = 12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        doing.forEach { s ->
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Filled.Check, contentDescription = null, tint = Brand, modifier = Modifier.size(20.dp))
                Text(stringResource(s), color = Ink, style = MaterialTheme.typography.bodyMedium)
            }
        }
        if (!state.cleared && (level == null || level == RiskLevel.NONE || level == RiskLevel.WATCH)) {
            Text(stringResource(TIPS[tip]), color = Muted, style = MaterialTheme.typography.bodyMedium)
        }
    }
}

private val TIPS = listOf(R.string.prompt_tip_otp, R.string.prompt_tip_police, R.string.prompt_tip_apps, R.string.prompt_tip_hurry, R.string.prompt_tip_family)

/** "I know this caller" / "It's not a scam": a plain text button, 48 dp tall, under the card's main button. */
@Composable
private fun FalseAlarmLink(text: String, onClick: () -> Unit) {
    TextButton(onClick, Modifier.padding(end = 12.dp).heightIn(min = 48.dp)) {
        Text(text, color = Ink, style = MaterialTheme.typography.bodyMedium, textDecoration = TextDecoration.Underline)
    }
}

/** The amber or red listener card: a headline with a warning sign, a line of advice if any, then its buttons. [onClose] adds ✕. */
@Composable
private fun RiskCard(fg: Color, bg: Color, headline: String, advice: String?, onClose: (() -> Unit)?, buttons: @Composable () -> Unit) {
    val shape = RoundedCornerShape(16.dp)
    Column(
        Modifier.padding(end = 12.dp).fillMaxWidth().background(bg, shape).border(2.dp, fg, shape).padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Icon(Icons.Filled.Warning, contentDescription = null, tint = fg, modifier = Modifier.size(28.dp))
            Text(headline, Modifier.weight(1f), color = if (fg == Red) Red else Ink, style = MaterialTheme.typography.titleSmall)
            if (onClose != null) {
                IconButton(onClose, Modifier.size(48.dp)) {
                    Icon(Icons.Filled.Close, contentDescription = stringResource(R.string.action_close), tint = Grey)
                }
            }
        }
        if (advice != null) Text(advice, color = Ink, style = MaterialTheme.typography.bodyMedium)
        buttons()
    }
}

/** The scam type in plain words: "This sounds like a 'digital arrest' scam." */
private fun ScamType.headline() = when (this) {
    ScamType.DIGITAL_ARREST -> R.string.scam_digital_arrest
    ScamType.BANK_KYC -> R.string.scam_bank_kyc
    ScamType.OTP_UPI -> R.string.scam_otp_upi
    ScamType.REMOTE_ACCESS -> R.string.scam_remote_access
    ScamType.FAMILY_EMERGENCY -> R.string.scam_family_emergency
    ScamType.COURIER_CUSTOMS -> R.string.scam_courier_customs
    ScamType.TRAI_SIM -> R.string.scam_trai_sim
    ScamType.JOB_TASK -> R.string.scam_job_task
    ScamType.INVESTMENT -> R.string.scam_investment
    ScamType.REWARD -> R.string.scam_reward
    ScamType.BOSS_PAYMENT -> R.string.scam_boss_payment
    ScamType.IMPERSONATION -> R.string.scam_impersonation
    ScamType.UNKNOWN -> R.string.scam_unknown
}

/** One line of advice for the scam type: "Police never ask for money on a call." */
private fun ScamType.advice() = when (this) {
    ScamType.DIGITAL_ARREST -> R.string.scam_digital_arrest_advice
    ScamType.BANK_KYC -> R.string.scam_bank_kyc_advice
    ScamType.OTP_UPI -> R.string.scam_otp_upi_advice
    ScamType.REMOTE_ACCESS -> R.string.scam_remote_access_advice
    ScamType.FAMILY_EMERGENCY -> R.string.scam_family_emergency_advice
    ScamType.COURIER_CUSTOMS -> R.string.scam_courier_customs_advice
    ScamType.TRAI_SIM -> R.string.scam_trai_sim_advice
    ScamType.JOB_TASK -> R.string.scam_job_task_advice
    ScamType.INVESTMENT -> R.string.scam_investment_advice
    ScamType.REWARD -> R.string.scam_reward_advice
    ScamType.BOSS_PAYMENT -> R.string.scam_boss_payment_advice
    ScamType.IMPERSONATION -> R.string.scam_impersonation_advice
    ScamType.UNKNOWN -> R.string.scam_unknown_advice
}

/** An unknown number: a small chip that opens the family's faces, to say who the caller claims to be. */
@Composable
private fun UnknownCaller(family: List<Member>, onPickMember: (String) -> Unit, onClose: () -> Unit, startPicking: Boolean = false) {
    var picking by remember { mutableStateOf(startPicking) }
    HeaderRow(onClose) {
        if (!picking) {
            OutlinedButton(
                { picking = true },
                Modifier.heightIn(min = 48.dp),
                shape = RoundedCornerShape(24.dp),
                border = BorderStroke(2.dp, Line),
            ) {
                Text(stringResource(R.string.card_family_chip), color = Ink, style = MaterialTheme.typography.labelLarge)
            }
        } else {
            Text(stringResource(R.string.card_pick_title), color = Ink, style = MaterialTheme.typography.titleSmall)
        }
    }
    if (picking) {
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            val colours = remember(family) { familyColours(family) }
            family.forEach { m ->
                MemberFace(
                    m,
                    Modifier.clickable(role = Role.Button, onClickLabel = stringResource(R.string.card_pick_action, m.label)) { onPickMember(m.id) },
                    size = 56.dp,
                    colour = colours.getValue(m.id),
                )
            }
        }
    }
}

/* ---- previews: every CALL_*, RING_* and LISTEN_* scenario from FakeRepository, over a stand-in dialer ---- */

private class CallScenarios : PreviewParameterProvider<Scenario> {
    override val values = Scenario.entries.filter { it.name.startsWith("CALL_") || it.name.startsWith("RING_") || it.name.startsWith("LISTEN_") }.asSequence()
}

private fun uiFor(s: Scenario): CallCheckUi {
    val repo = FakeRepository(s)
    val call = repo.call.value
    return CallCheckUi(call?.caller, call?.check, repo.home.value?.family.orEmpty(), call?.listen ?: ListenState.OFF, call?.onSpeaker ?: false, call?.risk, call?.cleared ?: false)
}

@Preview(name = "English", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Preview(name = "English, large font", locale = "en", widthDp = 360, heightDp = 800, fontScale = 1.5f)
@Composable
private fun CallCheckCardPreview(@PreviewParameter(CallScenarios::class) s: Scenario) = CsTheme {
    Box(Modifier.fillMaxSize().background(Color(0xFF1F2A33))) {
        // the dialer's end-call button, which the card must never cover
        Box(Modifier.align(Alignment.BottomCenter).padding(bottom = 48.dp).size(72.dp).background(Red, RoundedCornerShape(36.dp)))
        CallCheckCard(uiFor(s), {}, {}, {}, {})
    }
}

@Preview(name = "Picking a face", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Picking a face, Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Composable
private fun PickingPreview() = CsTheme {
    Box(Modifier.fillMaxSize().background(Color(0xFF1F2A33))) {
        Column(Modifier.padding(8.dp).background(Color.White, RoundedCornerShape(20.dp)).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            UnknownCaller(uiFor(Scenario.CALL_UNKNOWN_NUMBER).family, {}, {}, startPicking = true)
        }
    }
}

@Preview(name = "Cleared", locale = "en", widthDp = 360, heightDp = 400)
@Preview(name = "Cleared, Hindi", locale = "hi", widthDp = 360, heightDp = 400, fontScale = 1.5f)
@Composable
private fun ClearedPreview() = CsTheme {
    CallCheckCard(uiFor(Scenario.LISTEN_FALSE_ALARM).copy(risk = null, cleared = true), {}, {}, {}, {})
}
