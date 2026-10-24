package app.countersign.bank.ui.overlay

import android.annotation.SuppressLint
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Close
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
import app.countersign.bank.data.Member
import app.countersign.bank.data.Outcome
import app.countersign.bank.data.RingState
import app.countersign.bank.data.Scenario
import app.countersign.bank.data.Verdict
import app.countersign.bank.ui.CsTheme
import app.countersign.bank.ui.Grey
import app.countersign.bank.ui.Ink
import app.countersign.bank.ui.Line
import app.countersign.bank.ui.Red
import app.countersign.bank.ui.components.BigButton
import app.countersign.bank.ui.components.ButtonKind
import app.countersign.bank.ui.components.MemberFace
import app.countersign.bank.ui.components.VerdictChip
import kotlinx.coroutines.delay

/**
 * The card C shows over the dialer during a call: is the caller really who they say?
 *
 * State in, lambdas out, and no Activity: C hosts it in an overlay window from a service.
 * - An unknown number: the "Says they're family? Check" chip, then a row of faces; [onPickMember] gets the member id.
 * - A check: its verdict, and on ✗ or ? the Ring / Call buttons. A ✓ fades after 4 s and then calls [onClose].
 * - While a ring is out: "Ringing Rahul…", then what Rahul answered.
 *
 * It never takes more than the top third of the screen, so the dialer's end-call button stays free.
 * If large fonts make it taller than that, it scrolls.
 */
// The screen's height, not the window's: C's overlay window wraps the card, so its own size says nothing.
@SuppressLint("ConfigurationScreenWidthHeight")
@Composable
fun CallCheckCard(state: CallCheckUi, onRing: () -> Unit, onCall: () -> Unit, onPickMember: (String) -> Unit, onClose: () -> Unit) {
    val check = state.check
    val fades = check != null && check.ring == RingState.NONE && (check.verdict == Verdict.VERIFIED || check.verdict == Verdict.LIKELY)
    var shown by remember(check?.id) { mutableStateOf(true) }
    LaunchedEffect(check?.id, fades) {
        if (fades) {
            delay(4_000)
            shown = false
            delay(FADE_MS.toLong())
            onClose()
        }
    }

    // buzz once when a check turns ✗
    val haptics = LocalHapticFeedback.current
    LaunchedEffect(check?.id, check?.outcome) {
        if (check?.outcome == Outcome.DANGER) haptics.performHapticFeedback(HapticFeedbackType.LongPress)
    }

    val maxHeight = (LocalConfiguration.current.screenHeightDp / 3).dp
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
                if (check == null) UnknownCaller(state.family, onPickMember, onClose) else CheckBody(check, onRing, onCall, onClose)
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
private fun CheckBody(check: Check, onRing: () -> Unit, onCall: () -> Unit, onClose: () -> Unit) {
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
            family.forEach { m ->
                MemberFace(
                    m,
                    Modifier.clickable(role = Role.Button, onClickLabel = stringResource(R.string.card_pick_action, m.label)) { onPickMember(m.id) },
                    size = 56.dp,
                )
            }
        }
    }
}

/* ---- previews: every CALL_* and RING_* scenario from FakeRepository, over a stand-in dialer ---- */

private class CallScenarios : PreviewParameterProvider<Scenario> {
    override val values = Scenario.entries.filter { it.name.startsWith("CALL_") || it.name.startsWith("RING_") }.asSequence()
}

private fun uiFor(s: Scenario): CallCheckUi {
    val repo = FakeRepository(s)
    val call = repo.call.value
    return CallCheckUi(call?.caller, call?.check, repo.home.value?.family.orEmpty())
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
