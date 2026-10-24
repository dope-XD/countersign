package app.countersign.bank.ui

import androidx.activity.ComponentActivity
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountBox
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Email
import androidx.compose.material.icons.filled.Face
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Phone
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.countersign.bank.R
import app.countersign.bank.data.FakeRepository
import app.countersign.bank.data.Permission
import app.countersign.bank.data.Repository
import app.countersign.bank.data.Scenario
import app.countersign.bank.ui.components.BigButton
import app.countersign.bank.ui.components.LanguageSwitch
import kotlinx.coroutines.launch

/**
 * First run: language → about you → one permission card at a time → [onDone].
 *
 * Each step is worked out from what's already saved (language picked, signed in, permissions granted), not from a
 * counter, so it picks up in the right place after the language switch recreates the activity, or after a restart.
 */
@Composable
fun SetupFlow(repo: Repository, onDone: () -> Unit) {
    val context = LocalContext.current
    val signedIn by repo.signedIn.collectAsState()
    val permissions by repo.permissions.collectAsState()
    // plain remember, not saveable: after the language switch recreates the activity, this re-reads the saved choice
    var languagePicked by remember { mutableStateOf(Language.chosen(context)) }
    var skipped by rememberSaveable { mutableStateOf(listOf<String>()) }
    val nextPermission = permissions.missing.firstOrNull { it.name !in skipped }

    Box(Modifier.fillMaxSize().background(Paper)) {
        when {
            !languagePicked -> LanguageStep { languagePicked = true }
            !signedIn -> AboutYouStep(repo)
            nextPermission != null -> PermissionStep(
                permission = nextPermission,
                number = Permission.entries.size - permissions.missing.size + skipped.size + 1,
                of = Permission.entries.size,
                onAllow = { (context as? ComponentActivity)?.let { repo.request(nextPermission, it) } },
                onSkip = { skipped = skipped + nextPermission.name },
            )
            else -> LaunchedEffect(Unit) { onDone() }
        }
    }
}

/** A screen of setup: scrolls at large font sizes, one heading, then the step's own content. */
@Composable
private fun Step(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(
        Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp, vertical = 32.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        Text(title, Modifier.semantics { heading() }, color = Ink, style = MaterialTheme.typography.headlineLarge)
        content()
    }
}

@Composable
internal fun LanguageStep(onPicked: () -> Unit) = Step(stringResource(R.string.language_title)) {
    LanguageSwitch(onPicked = { onPicked() })
}

@Composable
internal fun AboutYouStep(repo: Repository) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var name by rememberSaveable { mutableStateOf("") }
    var mobile by rememberSaveable { mutableStateOf("") }
    var nameError by rememberSaveable { mutableStateOf(false) }
    var error by rememberSaveable { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }

    fun submit() {
        if (busy) return
        if (name.isBlank()) {
            nameError = true
            return
        }
        busy = true
        error = null
        scope.launch {
            // the repository's messages are written to be shown as they are
            try {
                repo.signUp(name.trim(), mobile.trim(), Language.current(context))
            } catch (e: Exception) {
                error = e.message
            }
            busy = false
        }
    }

    Step(stringResource(R.string.about_title)) {
        OutlinedTextField(
            name, { name = it; nameError = false },
            Modifier.fillMaxWidth(),
            label = { Text(stringResource(R.string.about_name)) },
            singleLine = true,
            textStyle = MaterialTheme.typography.bodyLarge,
            isError = nameError,
            supportingText = if (nameError) {
                { Text(stringResource(R.string.about_name_missing), color = Red, style = MaterialTheme.typography.bodyMedium) }
            } else {
                null
            },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
        )
        OutlinedTextField(
            mobile, { v -> mobile = v.filter { it.isDigit() || it == '+' || it == ' ' }; error = null },
            Modifier.fillMaxWidth(),
            label = { Text(stringResource(R.string.about_mobile)) },
            singleLine = true,
            textStyle = MaterialTheme.typography.bodyLarge,
            isError = error != null,
            supportingText = error?.let { { Text(it, color = Red, style = MaterialTheme.typography.bodyMedium) } },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone, imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { submit() }),
        )
        BigButton(stringResource(if (busy) R.string.about_wait else R.string.action_continue), { submit() }, enabled = !busy)
    }
}

private class PermissionCopy(val icon: ImageVector, val title: Int, val why: Int)

private fun Permission.copy() = when (this) {
    Permission.PHONE -> PermissionCopy(Icons.Filled.Phone, R.string.perm_phone, R.string.perm_phone_why)
    Permission.CALL_SCREENING -> PermissionCopy(Icons.Filled.Face, R.string.perm_screening, R.string.perm_screening_why)
    // OUTGOING_CALLS replaces CALL_REDIRECTION; both mean "the number this phone dials"
    Permission.CALL_REDIRECTION, Permission.OUTGOING_CALLS -> PermissionCopy(Icons.Filled.Call, R.string.perm_redirection, R.string.perm_redirection_why)
    Permission.MICROPHONE -> PermissionCopy(Icons.Filled.Phone, R.string.perm_microphone, R.string.perm_microphone_why)
    Permission.ACCESSIBILITY -> PermissionCopy(Icons.Filled.Info, R.string.perm_accessibility, R.string.perm_accessibility_why)
    Permission.SMS -> PermissionCopy(Icons.Filled.Email, R.string.perm_sms, R.string.perm_sms_why)
    Permission.NOTIFICATIONS -> PermissionCopy(Icons.Filled.Notifications, R.string.perm_notifications, R.string.perm_notifications_why)
    Permission.OVERLAY -> PermissionCopy(Icons.Filled.AccountBox, R.string.perm_overlay, R.string.perm_overlay_why)
    Permission.USAGE_ACCESS -> PermissionCopy(Icons.Filled.Lock, R.string.perm_usage, R.string.perm_usage_why)
    Permission.FULL_SCREEN -> PermissionCopy(Icons.Filled.Person, R.string.perm_full_screen, R.string.perm_full_screen_why)
    Permission.BATTERY -> PermissionCopy(Icons.Filled.Settings, R.string.perm_battery, R.string.perm_battery_why)
}

/** One permission: an icon, what it is, one line why, "Allow", and a small "Skip". The card moves on when it's granted. */
@Composable
internal fun PermissionStep(permission: Permission, number: Int, of: Int, onAllow: () -> Unit, onSkip: () -> Unit) {
    val copy = permission.copy()
    Step(stringResource(R.string.perm_heading)) {
        Text(stringResource(R.string.perm_progress, number.coerceAtMost(of), of), color = Muted, style = MaterialTheme.typography.bodyMedium)
        Card(
            Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(20.dp),
            colors = CardDefaults.cardColors(containerColor = Color.White),
        ) {
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Box(Modifier.size(72.dp).background(Brand.copy(alpha = 0.12f), CircleShape), contentAlignment = Alignment.Center) {
                    // the title below says what it is
                    Icon(copy.icon, contentDescription = null, tint = Brand, modifier = Modifier.size(40.dp))
                }
                Text(stringResource(copy.title), color = Ink, style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center)
                Text(stringResource(copy.why), color = Ink, style = MaterialTheme.typography.bodyLarge, textAlign = TextAlign.Center)
                Spacer(Modifier.heightIn(min = 4.dp))
                BigButton(stringResource(R.string.action_allow), onAllow)
            }
        }
        TextButton(onSkip, Modifier.align(Alignment.CenterHorizontally).heightIn(min = 48.dp)) {
            Text(stringResource(R.string.action_skip), color = Muted, style = MaterialTheme.typography.bodyLarge)
        }
    }
}

/* ---- previews: each step on FakeRepository's NEW_USER ---- */

private fun newUser() = FakeRepository(Scenario.NEW_USER)

@Preview(name = "English", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Preview(name = "English, large font", locale = "en", widthDp = 360, heightDp = 800, fontScale = 1.5f)
@Composable
private fun LanguageStepPreview() = CsTheme { Box(Modifier.background(Paper)) { LanguageStep {} } }

@Preview(name = "English", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Preview(name = "English, large font", locale = "en", widthDp = 360, heightDp = 800, fontScale = 1.5f)
@Composable
private fun AboutYouPreview() = CsTheme { Box(Modifier.background(Paper)) { AboutYouStep(newUser()) } }

@Preview(name = "English", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Preview(name = "English, large font", locale = "en", widthDp = 360, heightDp = 800, fontScale = 1.5f)
@Composable
private fun PermissionPreview() = CsTheme { Box(Modifier.background(Paper)) { PermissionStep(Permission.OVERLAY, 5, 8, {}, {}) } }
