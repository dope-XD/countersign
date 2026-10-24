package app.countersign.bank.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import app.countersign.bank.Api
import app.countersign.bank.ApiError
import app.countersign.bank.BankCall
import app.countersign.bank.Bus
import app.countersign.bank.MainActivity
import app.countersign.bank.Wav
import app.countersign.bank.objects
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

private data class Sample(val id: String, val label: String)

/**
 * Calling CS Bank from the app. "As myself" is the genuine customer. "Try an attack" calls as
 * someone else: you claim their number (as fraudsters spoof caller ID) and either do your best
 * impression or play a cloned-voice clip. The approval or code then goes to the real owner's
 * phone, which the attacker doesn't have.
 */
@Composable
fun CallScreen(activity: MainActivity, model: HomeModel, close: () -> Unit) {
    val scope = rememberCoroutineScope()
    val me = model.home?.account
    var attack by remember { mutableStateOf(false) }
    var claimed by remember { mutableStateOf("") }
    var lang by remember { mutableStateOf("en") }
    var samples by remember { mutableStateOf<List<Sample>>(emptyList()) }
    var sample by remember { mutableStateOf<Sample?>(null) }
    var inCall by remember { mutableStateOf(BankCall.active) }
    var state by remember { mutableStateOf("Calling…") }
    var tier by remember { mutableStateOf<String?>(null) }
    val scores = remember { mutableStateListOf<Double>() }
    val lines = remember { mutableStateListOf<Pair<Boolean, String>>() } // (is the bank, words)
    var leaked by remember { mutableStateOf<JSONObject?>(null) }
    var code by remember { mutableStateOf<String?>(null) }
    var result by remember { mutableStateOf<JSONObject?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var seconds by remember { mutableIntStateOf(0) }
    var speakerOn by remember { mutableStateOf(true) }
    var muted by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        samples = try {
            Api.getArray("/api/m/samples").objects().map { Sample(it.getString("id"), it.getString("label")) }
        } catch (e: ApiError) {
            emptyList()
        }
    }
    LaunchedEffect(Unit) {
        BankCall.events.collect { m ->
            when (m.optString("type")) {
                "local_state" -> when (m.optString("state")) {
                    "connected" -> state = "Ringing…"
                    "dropped" -> state = "Call dropped"
                    "ended" -> inCall = false
                }
                "answered" -> state = "Connected"
                "agent" -> lines.add(true to m.optString("say"))
                "caller" -> lines.add(false to m.optString("said"))
                "verdict" -> {
                    val ev = m.optJSONObject("event") ?: return@collect
                    when (ev.optString("type")) {
                        "window" -> scores.add(ev.optDouble("p"))
                        "state" -> ev.optJSONObject("call")?.let { c -> if (!c.isNull("tier")) tier = c.optString("tier") }
                    }
                }
                "result" -> result = m
                "busy", "error" -> error = m.optString("message")
            }
        }
    }
    LaunchedEffect(Unit) {
        Bus.events.collect { e -> if (e.optString("type") == "code") code = e.optString("code") }
    }
    LaunchedEffect(inCall) {
        while (inCall) {
            delay(1000)
            seconds++
        }
    }
    DisposableEffect(Unit) { onDispose { if (BankCall.active && result != null) BankCall.stop() } }

    fun dial() {
        error = null
        lines.clear()
        scores.clear()
        tier = null
        result = null
        code = null
        seconds = 0
        state = "Calling…"
        val cli = if (attack) "+91" + claimed else me?.mobile ?: ""
        val s = sample
        scope.launch {
            val clip = if (attack && s != null) {
                try {
                    withContext(Dispatchers.IO) {
                        val r = Api.http.newCall(Api.request("/api/m/samples/${s.id}").get().build()).execute()
                        r.use { Wav.to8k(it.body!!.bytes()) }
                    }
                } catch (e: Exception) {
                    error = "Couldn't load the clip: ${e.message}"
                    return@launch
                }
            } else {
                null
            }
            BankCall.start(activity, cli, lang, clip)
            inCall = true
        }
    }

    val mic = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) dial() else error = "CS Bank needs the microphone to call the bank."
    }

    Column(
        Modifier.fillMaxSize().background(Color(0xFF0E1A26)).systemBarsPadding().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text("CS Bank customer care", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            if (!inCall) TextButton(close) { Text("Close", color = Color.White) }
        }
        if (!inCall && result == null) {
            Text("Talk to CS Bank's virtual assistant. Ask for your balance, to block your card, or to change your registered mobile number.", color = Color(0xFFB8C7D4))
            listOf(false to "Call as myself", true to "Try an attack: call as someone else").forEach { (v, label) ->
                Row(Modifier.fillMaxWidth().selectable(attack == v) { attack = v }, verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(attack == v, { attack = v })
                    Text(label, color = Color.White, fontSize = 17.sp)
                }
            }
            if (attack) {
                Text("Fraudsters fake the caller ID. Whose number will you call from?", color = Color(0xFFB8C7D4))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    model.home?.family?.forEach { f ->
                        FilterChip(claimed == f.mobile.removePrefix("+91"), { claimed = f.mobile.removePrefix("+91") }, label = { Text(f.label) })
                    }
                }
                OutlinedTextField(
                    claimed, { claimed = it.filter { c -> c.isDigit() }.take(10) }, label = { Text("Their mobile number") }, prefix = { Text("+91 ") },
                    singleLine = true, modifier = Modifier.fillMaxWidth(),
                )
                LaunchedEffect(claimed) {
                    leaked = if (claimed.length == 10) runCatching { Api.get("/api/m/leaked?mobile=$claimed") }.getOrNull() else null
                }
                leaked?.let {
                    Banner(
                        "What a fraudster already has from leaks: ${it.optString("name")}, debit card ending ${it.optString("card_last4")}. " +
                            "Give these when asked. Watch what still stops you.",
                        Tone.Warn,
                    )
                }
                Text("Whose voice?", color = Color(0xFFB8C7D4))
                FilterChip(sample == null, { sample = null }, label = { Text("My own voice (do an impression)") })
                samples.forEach { s -> FilterChip(sample == s, { sample = s }, label = { Text("Cloned voice: ${s.label}") }) }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("en" to "English", "hi" to "Hindi", "hinglish" to "Hinglish").forEach { (k, v) -> FilterChip(lang == k, { lang = k }, label = { Text(v) }) }
            }
            error?.let { Banner(it, Tone.Danger) }
            Button({
                if (attack && sample != null) {
                    dial()
                } else if (ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                    dial()
                } else {
                    mic.launch(Manifest.permission.RECORD_AUDIO)
                }
            }, enabled = !attack || claimed.length == 10, modifier = Modifier.fillMaxWidth().height(56.dp), colors = ButtonDefaults.buttonColors(containerColor = Green)) {
                Text("Call", fontSize = 18.sp)
            }
            return@Column
        }

        Text(if (inCall) "$state  ·  ${seconds / 60}:${"%02d".format(seconds % 60)}" else "Call ended", color = Color(0xFFB8C7D4))
        VoiceCheck(tier, scores)
        code?.let {
            Column(Modifier.fillMaxWidth().background(Color.White, RoundedCornerShape(16.dp)).padding(16.dp)) {
                Text("Read this code to CS Bank", fontWeight = FontWeight.Bold)
                Text(it.chunked(2).joinToString("  "), fontSize = 40.sp, fontWeight = FontWeight.ExtraBold, color = Brand)
                Text("Only on a call you made to CS Bank. Never read it to anyone who called you.", color = Red, fontSize = 13.sp)
            }
        }
        lines.takeLast(5).forEach { (bank, l) ->
            Text(
                if (bank) "CS Bank: $l" else "You: $l",
                color = if (bank) Color.White else Color(0xFFB8C7D4), fontSize = 16.sp,
                modifier = Modifier.background(if (bank) Color(0xFF1C2D3D) else Color(0xFF13202C), RoundedCornerShape(12.dp)).padding(12.dp).fillMaxWidth(),
            )
        }
        if (attack) leaked?.let {
            Text("From a data leak: ${it.optString("name")}, card ending ${it.optString("card_last4")}", color = Color(0xFFFFC266), fontSize = 14.sp)
        }
        result?.let { r ->
            val outcome = r.optString("outcome")
            val (text, tone) = when (outcome) {
                "executed" -> "The change was made, after approval on the account holder's phone." to Tone.Ok
                "declined" -> "The account holder said no on their phone. Nothing changed, and a fraud case is open." to Tone.Danger
                "held" -> "Held: nothing changes on this call. The fraud team will follow up." to Tone.Warn
                else -> "Nothing was changed." to Tone.Info
            }
            Banner(text, tone, title = "Outcome")
        }
        error?.let { Banner(it, Tone.Danger) }
        if (inCall && attack && sample != null) {
            var typed by remember { mutableStateOf("") }
            Text("A fraudster types and the clone speaks. Here the clip is the voice; type its words:", color = Color(0xFFB8C7D4), fontSize = 13.sp)
            val leak = leaked?.optString("card_last4") ?: ""
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf("Change my mobile number to 9876543210", "It's $leak", "Yes").forEach { q ->
                    FilterChip(false, { BankCall.sendTyped(q) }, label = { Text(q, fontSize = 12.sp) })
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(typed, { typed = it }, singleLine = true, modifier = Modifier.weight(1f), placeholder = { Text("What the clone says") })
                Button({
                    BankCall.sendTyped(typed)
                    typed = ""
                }, enabled = typed.isNotBlank()) { Text("Say") }
            }
        }
        if (inCall) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton({
                    muted = !muted
                    BankCall.mute(muted)
                }, Modifier.weight(1f)) { Text(if (muted) "Unmute" else "Mute", color = Color.White) }
                OutlinedButton({
                    speakerOn = !speakerOn
                    BankCall.speaker(speakerOn)
                }, Modifier.weight(1f)) { Text(if (speakerOn) "Earpiece" else "Speaker", color = Color.White) }
            }
            Button({ BankCall.stop() }, Modifier.fillMaxWidth().height(56.dp), colors = ButtonDefaults.buttonColors(containerColor = Red)) { Text("Hang up", fontSize = 18.sp) }
        } else {
            Button({
                result = null
                close()
            }, Modifier.fillMaxWidth()) { Text("Done") }
        }
    }
}

/** What Countersign thinks of the caller's voice, live: the tier and the last few window scores. */
@Composable
private fun VoiceCheck(tier: String?, scores: List<Double>) {
    val (label, color) = when (tier) {
        "GREEN" -> "Voice check: no signs of a cloned voice" to Color(0xFF2E9E5B)
        "AMBER" -> "Voice check: unsure, extra checks needed" to Color(0xFFE0A100)
        "RED" -> "Voice check: likely a cloned or synthetic voice" to Color(0xFFD9433A)
        else -> "Voice check: listening…" to Color(0xFF6B7C8C)
    }
    Column(Modifier.fillMaxWidth().background(Color(0xFF1C2D3D), RoundedCornerShape(16.dp)).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.width(12.dp).height(12.dp).background(color, RoundedCornerShape(6.dp)))
            Spacer(Modifier.width(8.dp))
            Text(label, color = Color.White, fontWeight = FontWeight.SemiBold)
        }
        Row(Modifier.fillMaxWidth().height(36.dp), horizontalArrangement = Arrangement.spacedBy(3.dp), verticalAlignment = Alignment.Bottom) {
            scores.takeLast(24).forEach { p ->
                val c = if (p >= 0.7) Color(0xFFD9433A) else if (p >= 0.3) Color(0xFFE0A100) else Color(0xFF2E9E5B)
                Box(Modifier.weight(1f).fillMaxHeight(maxOf(0.08f, p.toFloat())).background(c, RoundedCornerShape(2.dp)))
            }
        }
        Text("Each bar is 4 seconds of the caller's voice: how synthetic it sounds.", color = Color(0xFF8DA0B2), fontSize = 12.sp)
    }
}
