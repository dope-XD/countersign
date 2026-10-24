package app.countersign.bank.ui

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.countersign.bank.R
import app.countersign.bank.data.Analysis
import app.countersign.bank.data.FakeRepository
import app.countersign.bank.data.Repository
import app.countersign.bank.data.RiskLevel
import app.countersign.bank.ui.components.BigButton
import app.countersign.bank.ui.components.ButtonKind
import app.countersign.bank.ui.components.SubScreen
import app.countersign.bank.ui.components.whyLine
import kotlinx.coroutines.launch

/**
 * "Check a recording or message": pick a call recording or paste a message, and the phone runs the same scam check
 * as on a live call (Repository.checkRecording / checkText). The result says how sure it is, why, and what it heard.
 * Nothing leaves the phone. This is also how a judge's spot-check kit is run on the phone.
 */
@Composable
fun CheckScreen(repo: Repository, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var text by rememberSaveable { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var result by remember { mutableStateOf<Pair<Analysis, Boolean>?>(null) }
    fun run(audio: Boolean, block: suspend () -> Analysis) {
        busy = true
        error = null
        scope.launch {
            try {
                result = block() to audio
            } catch (e: Exception) {
                error = e.message
            } finally {
                busy = false
            }
        }
    }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        if (uri != null) run(true) { repo.checkRecording(uri) }
    }
    CheckContent(
        text = text,
        onText = { text = it },
        busy = busy,
        error = error,
        result = result,
        onPickAudio = { pick.launch("audio/*") },
        onCheckText = { run(false) { repo.checkText(text) } },
        onAgain = {
            result = null
            text = ""
        },
        onBack = onBack,
    )
}

@Composable
internal fun CheckContent(
    text: String,
    onText: (String) -> Unit,
    busy: Boolean,
    error: String?,
    result: Pair<Analysis, Boolean>?,
    onPickAudio: () -> Unit,
    onCheckText: () -> Unit,
    onAgain: () -> Unit,
    onBack: () -> Unit,
) = SubScreen(stringResource(R.string.check_title), onBack) {
    if (result != null) {
        ResultCard(result.first, fromAudio = result.second)
        BigButton(stringResource(R.string.check_again), onAgain, kind = ButtonKind.Quiet)
        return@SubScreen
    }
    Text(stringResource(R.string.check_intro), color = Ink, style = MaterialTheme.typography.bodyLarge)
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Icon(Icons.Filled.Lock, contentDescription = null, tint = Green, modifier = Modifier.size(22.dp))
        Text(stringResource(R.string.check_privacy), color = Muted, style = MaterialTheme.typography.bodyMedium)
    }
    if (busy) {
        Row(Modifier.semantics { liveRegion = LiveRegionMode.Polite }, verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            CircularProgressIndicator(color = Brand)
            Text(stringResource(R.string.check_working), color = Ink, style = MaterialTheme.typography.bodyLarge)
        }
        return@SubScreen
    }
    BigButton(stringResource(R.string.check_pick_audio), onPickAudio, icon = Icons.Filled.PlayArrow)
    OutlinedTextField(
        text,
        onText,
        Modifier.fillMaxWidth().heightIn(min = 120.dp),
        label = { Text(stringResource(R.string.check_paste_hint), style = MaterialTheme.typography.bodyMedium) },
        textStyle = MaterialTheme.typography.bodyLarge,
    )
    BigButton(stringResource(R.string.check_text_button), onCheckText, kind = ButtonKind.Quiet, enabled = text.isNotBlank())
    if (error != null) Banner(error, Tone.Danger)
}

/** The verdict: icon + words + colour, why it fired, the voice check, and what was heard or read. */
@Composable
internal fun ResultCard(a: Analysis, fromAudio: Boolean) {
    val (fg, bg, title) = when (a.level) {
        RiskLevel.SCAM -> Triple(Red, RedSoft, R.string.check_result_scam)
        RiskLevel.WARN -> Triple(Amber, AmberSoft, R.string.check_result_warn)
        RiskLevel.WATCH -> Triple(Grey, GreySoft, R.string.check_result_watch)
        RiskLevel.NONE -> Triple(Green, GreenSoft, R.string.check_result_none)
    }
    val shape = RoundedCornerShape(18.dp)
    Column(
        Modifier.fillMaxWidth().background(bg, shape).border(2.dp, fg, shape).padding(18.dp).semantics { liveRegion = LiveRegionMode.Polite },
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Icon(
                if (a.level == RiskLevel.NONE) Icons.Filled.CheckCircle else Icons.Filled.Warning,
                contentDescription = stringResource(if (a.level == RiskLevel.NONE) R.string.cd_safe else R.string.cd_danger),
                tint = fg,
                modifier = Modifier.size(40.dp),
            )
            Text(stringResource(title), Modifier.semantics { heading() }, color = if (fg == Green || fg == Grey) Ink else fg, style = MaterialTheme.typography.headlineSmall)
        }
        if (a.level == RiskLevel.WARN || a.level == RiskLevel.SCAM) {
            Text(stringResource(alarmLine(a.type)), color = Ink, style = MaterialTheme.typography.bodyLarge)
        }
        whyLine(a.cues, max = 4)?.let { Text(it, color = Ink, style = MaterialTheme.typography.bodyMedium) }
        if (a.level == RiskLevel.NONE) Text(stringResource(R.string.check_result_none_hint), color = Ink, style = MaterialTheme.typography.bodyMedium)
        a.voiceClone?.let { v ->
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Filled.Info, contentDescription = null, tint = Ink, modifier = Modifier.size(22.dp))
                Text(stringResource(if (v >= 0.5f) R.string.check_voice_ai else R.string.check_voice_real), color = Ink, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
    Text(stringResource(if (fromAudio) R.string.check_heard else R.string.check_read), Modifier.semantics { heading() }, color = Ink, style = MaterialTheme.typography.titleSmall)
    Text(
        a.transcript.take(1200),
        Modifier.fillMaxWidth().background(Color.White, RoundedCornerShape(12.dp)).padding(14.dp),
        color = Muted,
        style = MaterialTheme.typography.bodyMedium,
    )
}

@Preview(name = "Start", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Start, Hindi", locale = "hi", widthDp = 360, heightDp = 800, fontScale = 1.5f)
@Composable
private fun CheckStartPreview() = CsTheme { CheckContent("", {}, false, null, null, {}, {}, {}, {}) }

@Preview(name = "Scam recording", locale = "en", widthDp = 360, heightDp = 900)
@Preview(name = "Scam recording, Hindi", locale = "hi", widthDp = 360, heightDp = 900)
@Preview(name = "Scam recording, large font", locale = "en", widthDp = 360, heightDp = 1100, fontScale = 1.5f)
@Composable
private fun CheckScamPreview() = CsTheme { CheckContent("", {}, false, null, FakeRepository.SCAM_ANALYSIS to true, {}, {}, {}, {}) }

@Preview(name = "Harmless recording", locale = "en", widthDp = 360, heightDp = 800)
@Preview(name = "Harmless recording, Hindi", locale = "hi", widthDp = 360, heightDp = 800)
@Composable
private fun CheckSafePreview() = CsTheme { CheckContent("", {}, false, null, FakeRepository.SAFE_ANALYSIS to true, {}, {}, {}, {}) }
