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
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.countersign.bank.R
import app.countersign.bank.data.Approval
import app.countersign.bank.data.ApprovalKind
import app.countersign.bank.data.FakeRepository
import app.countersign.bank.data.Scenario
import app.countersign.bank.ui.components.BigButton
import app.countersign.bank.ui.components.ButtonKind
import app.countersign.bank.ui.components.FaceCircle

/**
 * The asked member's phone, full screen: "Is it you on Mummy's call?" with "Yes, it's me" (green) and "No, not me" (red).
 * C's ApprovalActivity hosts it, rings, and asks for the fingerprint or screen lock after [onYes]; "No" needs nothing.
 *
 * A family check is worded here, in the phone's language. Any other kind shows the engine's own question and detail.
 */
@Composable
fun RingScreen(approval: Approval, onYes: () -> Unit, onNo: () -> Unit) {
    val familyCheck = approval.kind == ApprovalKind.CALL_CHECK
    Column(
        Modifier
            .fillMaxSize()
            .background(Paper)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 48.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        FaceCircle(approval.from, size = 120.dp)
        Text(
            if (familyCheck) stringResource(R.string.ring_question, approval.from) else approval.question,
            Modifier.semantics { heading() },
            color = Ink,
            style = MaterialTheme.typography.headlineLarge,
            textAlign = TextAlign.Center,
        )
        Text(
            if (familyCheck) stringResource(R.string.ring_detail, approval.from) else approval.detail,
            color = Muted,
            style = MaterialTheme.typography.bodyLarge,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(24.dp))
        BigButton(stringResource(R.string.action_yes_its_me), onYes, kind = ButtonKind.Yes, icon = Icons.Filled.Check)
        Text(stringResource(R.string.ring_yes_hint), color = Muted, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center)
        BigButton(stringResource(R.string.action_no_not_me), onNo, kind = ButtonKind.No, icon = Icons.Filled.Close)
    }
}

private fun askedByPapa(): Approval = FakeRepository(Scenario.I_AM_BEING_RUNG).home.value!!.approvals.first()

@Preview(name = "English", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Preview(name = "English, large font", locale = "en", widthDp = 360, heightDp = 800, fontScale = 1.5f)
@Composable
private fun RingScreenPreview() = CsTheme { RingScreen(askedByPapa(), {}, {}) }
