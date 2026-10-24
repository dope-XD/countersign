package app.countersign.bank.ui

import android.text.format.DateUtils
import androidx.activity.ComponentActivity
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.countersign.bank.BuildConfig
import app.countersign.bank.R
import app.countersign.bank.data.Circle
import androidx.compose.material.icons.filled.Search
import app.countersign.bank.data.Check
import app.countersign.bank.data.FakeRepository
import app.countersign.bank.data.Home
import app.countersign.bank.data.JoinRequest
import app.countersign.bank.data.Outcome
import app.countersign.bank.data.Permission
import app.countersign.bank.data.Permissions
import app.countersign.bank.data.Repository
import app.countersign.bank.data.Scam
import app.countersign.bank.data.Scenario
import app.countersign.bank.ui.components.BigButton
import app.countersign.bank.ui.components.ButtonKind
import app.countersign.bank.ui.components.MemberFace
import app.countersign.bank.ui.components.familyColours
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Home: the shield, join requests, the family's faces with "+ Add family", and the last 3 checks.
 * The gear opens Settings, a face opens that member, "See all" opens History.
 *
 * In debug builds a long press on the shield moves FakeRepository to its next scenario.
 */
@Composable
fun HomeScreen(repo: Repository, onAddFamily: () -> Unit, onMember: (String) -> Unit, onSettings: () -> Unit, onHistory: () -> Unit, onCheck: () -> Unit = {}) {
    val home by repo.home.collectAsState()
    val permissions by repo.permissions.collectAsState()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val h = home
    if (h == null) {
        // first load: keep asking; after a few seconds say so, with Retry (a free relay can take a minute to wake)
        var error by remember { mutableStateOf<String?>(null) }
        var attempt by remember { mutableIntStateOf(0) }
        LaunchedEffect(attempt) {
            error = null
            delay(4_000)
            error = runCatching { repo.refresh() }.exceptionOrNull()?.message
        }
        Column(
            Modifier.fillMaxSize().background(Paper).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            CircularProgressIndicator(color = Brand)
            error?.let {
                Text(it, color = Ink, style = MaterialTheme.typography.bodyLarge, textAlign = TextAlign.Center)
                BigButton(stringResource(R.string.action_retry), { attempt++ }, kind = ButtonKind.Quiet)
            }
        }
        return
    }
    HomeContent(
        home = h,
        permissions = permissions,
        onFix = { p -> (context as? ComponentActivity)?.let { repo.request(p, it) } },
        onNextScenario = (repo as? FakeRepository)?.takeIf { BuildConfig.DEBUG }?.let { fake -> { fake.next() } },
        onAccept = { r, label -> scope.launch { runCatching { repo.confirmJoin(r.customerId, label) } } },
        onDecline = { r -> scope.launch { runCatching { repo.declineJoin(r.customerId) } } },
        onDismissScam = { scope.launch { runCatching { repo.dismissScam() } } },
        onAddFamily = onAddFamily,
        onMember = onMember,
        onSettings = onSettings,
        onHistory = onHistory,
        onCheck = onCheck,
    )
}

/** Home drawn from plain state, so previews and the screen share it. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun HomeContent(
    home: Home,
    permissions: Permissions,
    onFix: (Permission) -> Unit,
    onNextScenario: (() -> Unit)?,
    onAccept: (JoinRequest, String) -> Unit,
    onDecline: (JoinRequest) -> Unit,
    onDismissScam: () -> Unit,
    onAddFamily: () -> Unit,
    onMember: (String) -> Unit,
    onSettings: () -> Unit,
    onHistory: () -> Unit,
    onCheck: () -> Unit = {},
) {
    Column(
        Modifier.fillMaxSize().background(Paper).safeDrawingPadding().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        // top bar: just the gear, right-aligned
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            IconButton(onSettings, Modifier.size(56.dp)) {
                Icon(Icons.Filled.Settings, contentDescription = stringResource(R.string.settings), tint = Ink, modifier = Modifier.size(30.dp))
            }
        }
        home.scam?.let { ScamBanner(it, onDismissScam) }
        home.joinRequests.forEach { JoinRequestCard(it, onAccept, onDecline) }
        Shield(permissions, onFix, onNextScenario)
        BigButton(stringResource(R.string.home_check_tile), onCheck, kind = ButtonKind.Quiet, icon = Icons.Filled.Search)

        val colours = remember(home.family) { familyColours(home.family) }
        Text(stringResource(R.string.home_family), Modifier.semantics { heading() }, color = Ink, style = MaterialTheme.typography.headlineSmall)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            home.family.filter { it.circle == Circle.FAMILY }.forEach { m ->
                MemberFace(m, Modifier.clickable(role = Role.Button) { onMember(m.id) }, colour = colours.getValue(m.id))
            }
            AddFamilyTile(onAddFamily)
        }
        val work = home.family.filter { it.circle == Circle.WORK }
        if (work.isNotEmpty()) {
            Text(stringResource(R.string.home_work), Modifier.semantics { heading() }, color = Ink, style = MaterialTheme.typography.headlineSmall)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                work.forEach { m -> MemberFace(m, Modifier.clickable(role = Role.Button) { onMember(m.id) }, colour = colours.getValue(m.id)) }
            }
        }

        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.home_recent), Modifier.weight(1f).semantics { heading() }, color = Ink, style = MaterialTheme.typography.headlineSmall)
            if (home.checks.isNotEmpty()) {
                TextButton(onHistory, Modifier.heightIn(min = 48.dp)) {
                    Text(stringResource(R.string.home_see_all), color = Brand, style = MaterialTheme.typography.labelLarge)
                }
            }
        }
        if (home.checks.isEmpty()) {
            Text(stringResource(R.string.home_no_checks), color = Muted, style = MaterialTheme.typography.bodyMedium)
        } else {
            Column(Modifier.fillMaxWidth().background(Color.White, RoundedCornerShape(16.dp)).padding(vertical = 4.dp)) {
                home.checks.take(3).forEach { CheckRow(it) }
            }
        }
    }
}

/** "You're protected", or "Some things need your OK" with the first missing permission to allow. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun Shield(permissions: Permissions, onFix: (Permission) -> Unit, onNextScenario: (() -> Unit)?) {
    val missing = permissions.missing.firstOrNull()
    val ok = missing == null
    val fg = if (ok) Green else Amber
    val shape = RoundedCornerShape(20.dp)
    Row(
        Modifier
            .fillMaxWidth()
            .border(2.dp, fg, shape)
            .background(if (ok) GreenSoft else AmberSoft, shape)
            .combinedClickable(
                enabled = !ok || onNextScenario != null,
                onClick = { missing?.let(onFix) },
                onLongClick = onNextScenario,
            )
            .padding(18.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Icon(if (ok) Icons.Filled.CheckCircle else Icons.Filled.Warning, contentDescription = null, tint = fg, modifier = Modifier.size(52.dp))
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(if (ok) R.string.home_protected else R.string.home_needs_ok), color = fg, style = MaterialTheme.typography.titleLarge)
            if (missing != null) {
                Text(stringResource(R.string.home_fix, stringResource(missing.title())), color = Ink, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

/** "+ Add family": the same size as a face, with a dashed-looking outline. */
@Composable
private fun AddFamilyTile(onClick: () -> Unit) {
    val label = stringResource(R.string.home_add_family)
    Column(
        Modifier.width(96.dp).clickable(role = Role.Button, onClick = onClick).clearAndSetSemantics { contentDescription = label },
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(Modifier.size(72.dp).border(BorderStroke(3.dp, Brand), CircleShape), contentAlignment = Alignment.Center) {
            Icon(Icons.Filled.Add, contentDescription = null, tint = Brand, modifier = Modifier.size(36.dp))
        }
        Text(label, color = Brand, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center)
    }
}

/** One past check: ✓ / ✗ / ? with words, the name, and how long ago. */
@Composable
internal fun CheckRow(check: Check) {
    val (fg, words) = when (check.outcome) {
        Outcome.SAFE -> Green to stringResource(R.string.history_safe)
        Outcome.DANGER -> Red to stringResource(R.string.history_danger)
        Outcome.UNKNOWN -> Grey to stringResource(R.string.verdict_cant_reach)
        Outcome.PENDING -> Grey to stringResource(R.string.history_pending)
    }
    val ago = DateUtils.getRelativeTimeSpanString(check.createdAt, System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS).toString()
    Row(
        Modifier.fillMaxWidth().heightIn(min = 64.dp).padding(horizontal = 16.dp, vertical = 8.dp).semantics(mergeDescendants = true) {},
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        OutcomeMark(check.outcome, fg)
        // the time sits by the name, so the words get the full width at large font sizes
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(check.label, Modifier.weight(1f), color = Ink, style = MaterialTheme.typography.titleSmall)
                Text(ago, color = Muted, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.End)
            }
            Text(words, color = fg, style = MaterialTheme.typography.bodyMedium)
        }
    }
}

/** ✓, ✗ or ? in a filled circle (decorative: the words next to it say the same). */
@Composable
private fun OutcomeMark(outcome: Outcome, colour: Color) {
    Box(Modifier.size(36.dp).background(colour, CircleShape), contentAlignment = Alignment.Center) {
        when (outcome) {
            Outcome.SAFE -> Icon(Icons.Filled.Check, contentDescription = null, tint = Color.White, modifier = Modifier.size(24.dp))
            Outcome.DANGER -> Icon(Icons.Filled.Close, contentDescription = null, tint = Color.White, modifier = Modifier.size(24.dp))
            else -> Text("?", color = Color.White, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleSmall)
        }
    }
}

/** "Neha Gupta wants to join your family": Accept asks what I call them, then confirms. */
@Composable
private fun JoinRequestCard(request: JoinRequest, onAccept: (JoinRequest, String) -> Unit, onDecline: (JoinRequest) -> Unit) {
    var naming by rememberSaveable(request.customerId) { mutableStateOf(false) }
    Column(
        Modifier.fillMaxWidth().background(Color.White, RoundedCornerShape(20.dp)).border(2.dp, Brand, RoundedCornerShape(20.dp)).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text(stringResource(R.string.home_join_title, request.name), color = Ink, style = MaterialTheme.typography.titleMedium)
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            BigButton(stringResource(R.string.action_accept), { naming = true }, Modifier.weight(1f), kind = ButtonKind.Yes)
            BigButton(stringResource(R.string.action_no), { onDecline(request) }, Modifier.weight(1f), kind = ButtonKind.Quiet)
        }
    }
    if (naming) NameThemDialog(onSave = { onAccept(request, it); naming = false }, onCancel = { naming = false })
}

/** "What do you call them?" — the label this phone shows for the new member: "Rahul", "Mummy". */
@Composable
internal fun NameThemDialog(onSave: (String) -> Unit, onCancel: () -> Unit) {
    var label by rememberSaveable { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text(stringResource(R.string.join_label_title), style = MaterialTheme.typography.headlineSmall) },
        text = {
            OutlinedTextField(
                label, { label = it },
                Modifier.fillMaxWidth(),
                placeholder = { Text(stringResource(R.string.join_label_hint)) },
                singleLine = true,
                textStyle = MaterialTheme.typography.bodyLarge,
            )
        },
        confirmButton = {
            TextButton({ onSave(label.trim()) }, Modifier.heightIn(min = 48.dp), enabled = label.isNotBlank()) {
                Text(stringResource(R.string.action_save), style = MaterialTheme.typography.labelLarge)
            }
        },
        dismissButton = {
            TextButton(onCancel, Modifier.heightIn(min = 48.dp)) { Text(stringResource(R.string.action_cancel), style = MaterialTheme.typography.labelLarge) }
        },
    )
}

/** While a scam call is on (or just was): a red reminder, with "I understand" to put it away. */
@Composable
private fun ScamBanner(scam: Scam, onDismiss: () -> Unit) {
    Column(
        Modifier.fillMaxWidth().background(RedSoft, RoundedCornerShape(20.dp)).border(2.dp, Red, RoundedCornerShape(20.dp)).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Icon(Icons.Filled.Warning, contentDescription = null, tint = Red, modifier = Modifier.size(32.dp))
            Text(stringResource(R.string.home_scam, scam.label), color = Red, style = MaterialTheme.typography.titleMedium)
        }
        BigButton(stringResource(R.string.action_understood), onDismiss, kind = ButtonKind.Quiet)
    }
}

/* ---- previews: FakeRepository's IDLE, JOIN_REQUEST, PAY_GUARD and a missing permission ---- */

private fun homeOf(s: Scenario) = FakeRepository(s).home.value!!

@Composable
private fun HomePreviewOf(home: Home, permissions: Permissions = Permissions(Permission.entries.toSet())) = CsTheme {
    HomeContent(home, permissions, {}, null, { _, _ -> }, {}, {}, {}, {}, {}, {})
}

@Preview(name = "English", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Preview(name = "English, large font", locale = "en", widthDp = 360, heightDp = 800, fontScale = 1.5f)
@Composable
private fun HomeIdlePreview() = HomePreviewOf(homeOf(Scenario.IDLE))

@Preview(name = "Join request", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Join request, Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Composable
private fun HomeJoinPreview() = HomePreviewOf(homeOf(Scenario.JOIN_REQUEST))

@Preview(name = "Scam on, a permission missing", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Scam on, a permission missing, Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Composable
private fun HomeScamPreview() = HomePreviewOf(
    homeOf(Scenario.PAY_GUARD),
    Permissions(Permission.entries.toSet() - Permission.OVERLAY),
)
