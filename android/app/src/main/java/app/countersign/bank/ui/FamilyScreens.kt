package app.countersign.bank.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Share
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.countersign.bank.R
import app.countersign.bank.data.FakeRepository
import app.countersign.bank.data.Invite
import app.countersign.bank.data.Member
import app.countersign.bank.data.Repository
import app.countersign.bank.data.Scenario
import app.countersign.bank.ui.components.BigButton
import app.countersign.bank.ui.components.ButtonKind
import app.countersign.bank.ui.components.FaceCircle
import app.countersign.bank.ui.components.QrCode
import app.countersign.bank.ui.components.SubScreen
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import kotlinx.coroutines.launch

/** The steps of Add family. A code from a scanned invite link starts at [Name]. */
internal enum class AddStep { Choose, Show, Type, Name, Waiting }

/**
 * Add family: "Show my code" (a QR and 6 big digits) or "Scan their code" (or type it), then
 * "What do you call them?", then "Waiting for them to accept…". [code] comes from a scanned
 * csbank://family link, if the app was opened by one.
 */
@Composable
fun AddFamilyScreen(repo: Repository, code: String?, onDone: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var step by rememberSaveable { mutableStateOf(if (code != null) AddStep.Name else AddStep.Choose) }
    var theirCode by rememberSaveable { mutableStateOf(code.orEmpty()) }
    var invite by remember { mutableStateOf<Invite?>(null) }
    var error by rememberSaveable { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scanFailed = stringResource(R.string.add_scan_failed)

    // back goes to the first choice, then home
    BackHandler(step != AddStep.Choose && step != AddStep.Waiting) { step = AddStep.Choose; error = null }
    val back = { if (step == AddStep.Choose || step == AddStep.Waiting) onDone() else { step = AddStep.Choose; error = null } }

    LaunchedEffect(step) {
        if (step == AddStep.Show && invite == null) {
            invite = runCatching { repo.invite() }.onFailure { error = it.message }.getOrNull()
        }
    }

    fun scan() {
        val options = GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build()
        GmsBarcodeScanning.getClient(context, options).startScan()
            .addOnSuccessListener { b ->
                val found = Regex("\\d{6}").find(b.rawValue.orEmpty())?.value
                if (found != null) {
                    theirCode = found
                    error = null
                    step = AddStep.Name
                } else {
                    error = scanFailed
                }
            }
    }

    AddFamilyContent(
        step = step,
        invite = invite,
        theirCode = theirCode,
        error = error,
        busy = busy,
        onBack = back,
        onShow = { error = null; step = AddStep.Show },
        onScan = { error = null; scan() },
        onType = { error = null; step = AddStep.Type },
        onCode = { theirCode = it.filter(Char::isDigit).take(6); error = null },
        onCodeDone = { step = AddStep.Name },
        onJoin = { label ->
            busy = true
            scope.launch {
                runCatching { repo.join(theirCode, label) }
                    .onSuccess { step = AddStep.Waiting; error = null }
                    .onFailure { error = it.message }
                busy = false
            }
        },
        onDone = onDone,
    )
}

/** Add family drawn from plain state, so previews can show each step. */
@Composable
internal fun AddFamilyContent(
    step: AddStep,
    invite: Invite?,
    theirCode: String,
    error: String?,
    busy: Boolean,
    onBack: () -> Unit,
    onShow: () -> Unit,
    onScan: () -> Unit,
    onType: () -> Unit,
    onCode: (String) -> Unit,
    onCodeDone: () -> Unit,
    onJoin: (String) -> Unit,
    onDone: () -> Unit,
) = SubScreen(stringResource(R.string.home_add_family), onBack) {
    when (step) {
        AddStep.Choose -> {
            Text(stringResource(R.string.add_choose_line), color = Ink, style = MaterialTheme.typography.bodyLarge)
            BigButton(stringResource(R.string.add_show_code), onShow, icon = Icons.Filled.Share)
            BigButton(stringResource(R.string.add_scan_code), onScan, kind = ButtonKind.Quiet, icon = Icons.Filled.Search)
            TextButton(onType, Modifier.align(Alignment.CenterHorizontally).heightIn(min = 48.dp)) {
                Text(stringResource(R.string.add_type_instead), color = Brand, style = MaterialTheme.typography.bodyLarge)
            }
        }
        AddStep.Show -> {
            if (invite == null) {
                if (error == null) CircularProgressIndicator(Modifier.align(Alignment.CenterHorizontally), color = Brand)
            } else {
                val minutes = ((invite.expiresAt - System.currentTimeMillis()) / 60_000).coerceAtLeast(1).toInt()
                Text(stringResource(R.string.add_show_line), color = Ink, style = MaterialTheme.typography.bodyLarge)
                Column(
                    Modifier.fillMaxWidth().background(Color.White, RoundedCornerShape(20.dp)).padding(20.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    QrCode(invite.qr, stringResource(R.string.add_qr_description))
                    // "482 913": two groups of three are easier to read out over the phone
                    Text(
                        invite.code.chunked(3).joinToString(" "),
                        color = Ink, fontSize = 44.sp, fontWeight = FontWeight.Bold, letterSpacing = 4.sp,
                    )
                    Text(
                        pluralStringResource(R.plurals.add_code_lasts, minutes, minutes),
                        color = Muted, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center,
                    )
                }
                Text(stringResource(R.string.add_show_after), color = Muted, style = MaterialTheme.typography.bodyMedium)
                BigButton(stringResource(R.string.action_done), onDone)
            }
        }
        AddStep.Type -> {
            OutlinedTextField(
                theirCode, onCode,
                Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.add_type_label)) },
                singleLine = true,
                textStyle = MaterialTheme.typography.headlineMedium.copy(letterSpacing = 6.sp),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
            )
            BigButton(stringResource(R.string.action_continue), onCodeDone, enabled = theirCode.length == 6)
        }
        AddStep.Name -> {
            var label by rememberSaveable { mutableStateOf("") }
            Text(stringResource(R.string.join_label_title), color = Ink, style = MaterialTheme.typography.titleLarge)
            OutlinedTextField(
                label, { label = it },
                Modifier.fillMaxWidth(),
                placeholder = { Text(stringResource(R.string.join_label_hint)) },
                singleLine = true,
                textStyle = MaterialTheme.typography.bodyLarge,
            )
            BigButton(
                stringResource(if (busy) R.string.about_wait else R.string.action_continue),
                { onJoin(label.trim()) },
                enabled = !busy && label.isNotBlank(),
            )
        }
        AddStep.Waiting -> {
            CircularProgressIndicator(Modifier.align(Alignment.CenterHorizontally).size(56.dp), color = Brand, strokeWidth = 5.dp)
            Text(stringResource(R.string.add_waiting), color = Ink, style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
            Text(stringResource(R.string.add_waiting_line), color = Muted, style = MaterialTheme.typography.bodyLarge, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
            BigButton(stringResource(R.string.action_done), onDone)
        }
    }
    if (error != null) Text(error, color = Red, style = MaterialTheme.typography.bodyMedium)
}

/** A family member: big face, online or not, and "Remove from family" (after a confirm). */
@Composable
fun MemberScreen(member: Member, colour: Color, onRemove: () -> Unit, onBack: () -> Unit) {
    var confirming by rememberSaveable { mutableStateOf(false) }
    SubScreen(member.label, onBack) {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
            FaceCircle(member.label, key = member.id, size = 140.dp, colour = colour)
            Text(member.label, color = Ink, style = MaterialTheme.typography.headlineLarge)
            if (member.name != member.label) Text(member.name, color = Muted, style = MaterialTheme.typography.bodyLarge)
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Box(Modifier.size(14.dp).background(if (member.online) Green else Grey, CircleShape))
                Text(
                    stringResource(if (member.online) R.string.member_online else R.string.member_offline),
                    color = if (member.online) Green else Grey, style = MaterialTheme.typography.bodyLarge,
                )
            }
            if (member.newLink) {
                Text(stringResource(R.string.member_new_link), color = Muted, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center)
            }
        }
        BigButton(stringResource(R.string.member_remove), { confirming = true }, kind = ButtonKind.Quiet)
    }
    if (confirming) {
        AlertDialog(
            onDismissRequest = { confirming = false },
            title = { Text(stringResource(R.string.member_remove_title, member.label), style = MaterialTheme.typography.headlineSmall) },
            text = { Text(stringResource(R.string.member_remove_line), style = MaterialTheme.typography.bodyLarge) },
            confirmButton = {
                TextButton({ confirming = false; onRemove() }, Modifier.heightIn(min = 48.dp)) {
                    Text(stringResource(R.string.member_remove_yes), color = Red, style = MaterialTheme.typography.labelLarge)
                }
            },
            dismissButton = {
                TextButton({ confirming = false }, Modifier.heightIn(min = 48.dp)) { Text(stringResource(R.string.action_cancel), style = MaterialTheme.typography.labelLarge) }
            },
        )
    }
}

/* ---- previews ---- */

private val previewInvite = Invite("482913", System.currentTimeMillis() + 600_000, "csbank://family?code=482913")

@Composable
private fun AddPreview(step: AddStep, code: String = "") = CsTheme {
    AddFamilyContent(step, previewInvite, code, null, false, {}, {}, {}, {}, {}, {}, {}, {})
}

@Preview(name = "English", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Preview(name = "English, large font", locale = "en", widthDp = 360, heightDp = 800, fontScale = 1.5f)
@Composable
private fun AddChoosePreview() = AddPreview(AddStep.Choose)

@Preview(name = "English", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Preview(name = "English, large font", locale = "en", widthDp = 360, heightDp = 800, fontScale = 1.5f)
@Composable
private fun AddShowPreview() = AddPreview(AddStep.Show)

@Preview(name = "English", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Composable
private fun AddWaitingPreview() = AddPreview(AddStep.Waiting)

private fun rahul() = FakeRepository(Scenario.IDLE).home.value!!.family.first()

@Preview(name = "English", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Preview(name = "English, large font", locale = "en", widthDp = 360, heightDp = 800, fontScale = 1.5f)
@Composable
private fun MemberPreview() = CsTheme { MemberScreen(rahul(), Brand, {}, {}) }
