package app.countersign.bank.ui

import androidx.activity.ComponentActivity
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.countersign.bank.R
import app.countersign.bank.data.CheckChannel
import app.countersign.bank.data.FakeRepository
import app.countersign.bank.data.Lang
import app.countersign.bank.data.Me
import app.countersign.bank.data.Permission
import app.countersign.bank.data.Permissions
import app.countersign.bank.data.Repository
import app.countersign.bank.data.Scenario
import app.countersign.bank.ui.components.BigButton
import app.countersign.bank.ui.components.ButtonKind
import app.countersign.bank.ui.components.LanguageSwitch
import app.countersign.bank.ui.components.SubScreen
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.launch

// Saving a setting outlives the screen: picking a language recreates the activity straight away.
private val saving = MainScope()

/** Settings: language, how family checks reach me, sharing call status, permissions, sign out. */
@Composable
fun SettingsScreen(repo: Repository, onBack: () -> Unit) {
    val home by repo.home.collectAsState()
    val permissions by repo.permissions.collectAsState()
    val context = LocalContext.current
    val me = home?.me ?: return
    SettingsContent(
        me = me,
        permissions = permissions,
        onLang = { lang -> saving.launch { runCatching { repo.setPrefs(lang = lang) } } },
        onChannel = { c -> saving.launch { runCatching { repo.setPrefs(channel = c) } } },
        onShare = { on -> saving.launch { runCatching { repo.setPrefs(shareCallStatus = on) } } },
        onAllow = { p -> (context as? ComponentActivity)?.let { repo.request(p, it) } },
        onSignOut = { repo.signOut() },
        onBack = onBack,
    )
}

@Composable
internal fun SettingsContent(
    me: Me,
    permissions: Permissions,
    onLang: (Lang) -> Unit,
    onChannel: (CheckChannel) -> Unit,
    onShare: (Boolean) -> Unit,
    onAllow: (Permission) -> Unit,
    onSignOut: () -> Unit,
    onBack: () -> Unit,
) = SubScreen(stringResource(R.string.settings), onBack) {
    var confirmSignOut by rememberSaveable { mutableStateOf(false) }

    Group(stringResource(R.string.language_setting)) {
        LanguageSwitch(onPicked = onLang)
    }

    Group(stringResource(R.string.settings_channel)) {
        Column(Modifier.selectableGroup()) {
            Choice(stringResource(R.string.settings_channel_ring), me.channel == CheckChannel.RING) { onChannel(CheckChannel.RING) }
            Choice(stringResource(R.string.settings_channel_notify), me.channel == CheckChannel.NOTIFY) { onChannel(CheckChannel.NOTIFY) }
        }
    }

    Group(stringResource(R.string.settings_share)) {
        Row(
            Modifier.fillMaxWidth().heightIn(min = 56.dp)
                .toggleable(me.shareCallStatus, role = Role.Switch, onValueChange = onShare),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(stringResource(R.string.settings_share_why), Modifier.weight(1f), color = Ink, style = MaterialTheme.typography.bodyMedium)
            // the row is the toggle, so the switch itself takes no clicks
            Switch(me.shareCallStatus, null, colors = SwitchDefaults.colors(checkedTrackColor = Green))
        }
    }

    Group(stringResource(R.string.settings_permissions)) {
        val missing = permissions.missing
        if (missing.isEmpty()) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Icon(Icons.Filled.CheckCircle, contentDescription = null, tint = Green, modifier = Modifier.size(28.dp))
                Text(stringResource(R.string.settings_all_allowed), color = Green, style = MaterialTheme.typography.bodyLarge)
            }
        } else {
            missing.forEach { p ->
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(stringResource(p.title()), Modifier.weight(1f), color = Ink, style = MaterialTheme.typography.bodyLarge)
                    TextButton({ onAllow(p) }, Modifier.heightIn(min = 48.dp)) {
                        Text(stringResource(R.string.action_allow), color = Brand, style = MaterialTheme.typography.labelLarge)
                    }
                }
            }
        }
    }

    BigButton(stringResource(R.string.settings_sign_out), { confirmSignOut = true }, kind = ButtonKind.Quiet)

    if (confirmSignOut) {
        AlertDialog(
            onDismissRequest = { confirmSignOut = false },
            title = { Text(stringResource(R.string.settings_sign_out_title), style = MaterialTheme.typography.headlineSmall) },
            text = { Text(stringResource(R.string.settings_sign_out_line), style = MaterialTheme.typography.bodyLarge) },
            confirmButton = {
                TextButton({ confirmSignOut = false; onSignOut() }, Modifier.heightIn(min = 48.dp)) {
                    Text(stringResource(R.string.settings_sign_out), color = Red, style = MaterialTheme.typography.labelLarge)
                }
            },
            dismissButton = {
                TextButton({ confirmSignOut = false }, Modifier.heightIn(min = 48.dp)) { Text(stringResource(R.string.action_cancel), style = MaterialTheme.typography.labelLarge) }
            },
        )
    }
}

/** A white card with a heading: one setting. */
@Composable
private fun Group(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(
        Modifier.fillMaxWidth().background(Color.White, RoundedCornerShape(20.dp)).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(title, Modifier.semantics { heading() }, color = Ink, style = MaterialTheme.typography.titleMedium)
        content()
    }
}

/** One of a set of choices: a radio button and its words, the whole row tappable. */
@Composable
private fun Choice(text: String, selected: Boolean, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 56.dp).selectable(selected, role = Role.RadioButton, onClick = onClick),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        RadioButton(selected, null, colors = RadioButtonDefaults.colors(selectedColor = Brand))
        Text(text, color = Ink, style = MaterialTheme.typography.bodyLarge)
    }
}

/* ---- previews ---- */

private fun me() = FakeRepository(Scenario.IDLE).home.value!!.me

@Preview(name = "English", locale = "en", widthDp = 360, heightDp = 1100)
@Preview(name = "Hindi", locale = "hi", widthDp = 360, heightDp = 1100)
@Preview(name = "English, large font", locale = "en", widthDp = 360, heightDp = 1400, fontScale = 1.5f)
@Composable
private fun SettingsPreview() = CsTheme {
    SettingsContent(me(), Permissions(Permission.entries.toSet() - Permission.OVERLAY - Permission.BATTERY), {}, {}, {}, {}, {}, {})
}
