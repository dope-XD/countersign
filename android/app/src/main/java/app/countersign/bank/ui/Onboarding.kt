package app.countersign.bank.ui

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.countersign.bank.Api
import app.countersign.bank.ApiError
import app.countersign.bank.CallWatchService
import app.countersign.bank.DeviceKey
import app.countersign.bank.Notify
import app.countersign.bank.Prefs
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Opening an account: who you are, how family checks reach you, and this phone's key. Three screens. */
@Composable
fun Onboarding(onDone: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var step by remember { mutableIntStateOf(0) }
    var name by remember { mutableStateOf("") }
    var mobile by remember { mutableStateOf("") }
    var ring by remember { mutableStateOf(true) }
    var share by remember { mutableStateOf(true) }
    var server by remember { mutableStateOf(Prefs.server) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var team by remember { mutableStateOf(false) }
    var teamWho by remember { mutableStateOf("rahul") }
    var pin by remember { mutableStateOf("") }

    val permissions = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { onDone() }

    fun finish(token: String, customer: String) {
        Prefs.token = token
        Prefs.customerId = customer
        CallWatchService.start(ctx)
        // full-screen "ring" for family checks, and keep the alerts alive in the background
        if (!Notify.canRing(ctx) && Build.VERSION.SDK_INT >= 34) {
            ctx.startActivity(Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:${ctx.packageName}")))
        }
        val pm = ctx.getSystemService(PowerManager::class.java)
        if (!pm.isIgnoringBatteryOptimizations(ctx.packageName)) {
            runCatching { ctx.startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${ctx.packageName}"))) }
        }
        val asks = mutableListOf(Manifest.permission.READ_PHONE_STATE, Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= 33) asks += Manifest.permission.POST_NOTIFICATIONS
        permissions.launch(asks.toTypedArray())
    }

    fun submit() {
        error = null
        if (!DeviceKey.screenLockSet(ctx)) {
            error = "Set a screen lock (PIN, pattern or fingerprint) on this phone first. Your approvals are protected by it."
            return
        }
        busy = true
        Prefs.server = server
        scope.launch {
            try {
                val key = DeviceKey.create()
                val device = "${Build.MANUFACTURER} ${Build.MODEL}"
                val r = if (team) {
                    Api.post("/api/m/claim", JSONObject().put("customer_id", teamWho).put("public_key", key).put("device", device), mapOf("X-Staff-Pin" to pin))
                } else {
                    Api.post(
                        "/api/m/signup",
                        JSONObject().put("name", name).put("mobile", mobile).put("check_channel", if (ring) "ring" else "notify")
                            .put("share_call_status", share).put("public_key", key).put("device", device),
                    )
                }
                finish(r.getString("token"), r.getJSONObject("account").getString("id"))
            } catch (e: ApiError) {
                error = e.message
            } catch (e: Exception) {
                error = "This phone couldn't make its key: ${e.message}"
            } finally {
                busy = false
            }
        }
    }

    Column(
        Modifier.fillMaxSize().systemBarsPadding().imePadding().verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("CS Bank", fontSize = 34.sp, fontWeight = FontWeight.ExtraBold, color = Brand)
        when (step) {
            0 -> {
                Text("A demo bank protected by Countersign.", fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
                Text(
                    "A cloned voice can sound exactly like you or your family. CS Bank never trusts a voice alone: anything risky needs " +
                        "a yes from the right person's phone.",
                    color = Muted,
                )
                Banner("You'll get a demo account with ₹2,50,000. No real money, no real bank details.", Tone.Info)
                if (team) {
                    Text("Team demo account", fontWeight = FontWeight.Bold)
                    listOf("rahul" to "Rahul Sharma", "sunita" to "Sunita Sharma").forEach { (id, label) ->
                        Row(Modifier.selectable(teamWho == id) { teamWho = id }, verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(teamWho == id, { teamWho = id })
                            Text(label)
                        }
                    }
                    OutlinedTextField(pin, { pin = it }, label = { Text("Staff PIN") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword), modifier = Modifier.fillMaxWidth())
                    OutlinedTextField(server, { server = it }, label = { Text("Bank server") }, modifier = Modifier.fillMaxWidth())
                    error?.let { Banner(it, Tone.Danger) }
                    Button({ submit() }, enabled = !busy && pin.isNotBlank(), modifier = Modifier.fillMaxWidth().height(52.dp)) { Text("Use this account") }
                    TextButton({ team = false }) { Text("Back") }
                } else {
                    Button({ step = 1 }, modifier = Modifier.fillMaxWidth().height(52.dp)) { Text("Open an account", fontSize = 17.sp) }
                    TextButton({ team = true }) { Text("Team demo account (staff PIN)") }
                }
            }
            1 -> {
                Text("About you", fontSize = 22.sp, fontWeight = FontWeight.Bold)
                OutlinedTextField(name, { name = it }, label = { Text("Your name") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(
                    mobile, { mobile = it.filter { c -> c.isDigit() }.take(10) },
                    label = { Text("Your mobile number") }, prefix = { Text("+91 ") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone), modifier = Modifier.fillMaxWidth(),
                    supportingText = { Text("Your real number: family will call you on it when they need to check.") },
                )
                Button({ step = 2 }, enabled = name.trim().length >= 2 && mobile.length == 10, modifier = Modifier.fillMaxWidth().height(52.dp)) { Text("Next") }
            }
            2 -> {
                Text("When family needs to check with you", fontSize = 22.sp, fontWeight = FontWeight.Bold)
                Text("If someone asks your family for money pretending to be you, CS Bank asks you first: \"Did you ask for this?\"", color = Muted)
                listOf(true to "Ring my phone, like a call", false to "Send a notification").forEach { (v, label) ->
                    Row(Modifier.fillMaxWidth().selectable(ring == v) { ring = v }, verticalAlignment = Alignment.CenterVertically) {
                        RadioButton(ring == v, { ring = v })
                        Text(label, fontSize = 17.sp)
                    }
                }
                Row(verticalAlignment = Alignment.Top) {
                    Checkbox(share, { share = it })
                    Column {
                        Text("Tell family whether I'm on a call", fontWeight = FontWeight.SemiBold)
                        Text(
                            "Only \"on a call: yes or no\", and only while one of them is checking with you. Never who you're talking to. You can turn this off any time.",
                            color = Muted, fontSize = 14.sp,
                        )
                    }
                }
                Button({ step = 3 }, modifier = Modifier.fillMaxWidth().height(52.dp)) { Text("Next") }
            }
            3 -> {
                Text("Protect this phone", fontSize = 22.sp, fontWeight = FontWeight.Bold)
                Text(
                    "CS Bank makes a key inside this phone's secure hardware. It never leaves the phone, and it only works with your fingerprint " +
                        "or screen lock. That's how the bank knows a \"yes\" really came from you.",
                    color = Muted,
                )
                Text("Next, allow notifications, phone state (only whether you're on a call, never who) and the microphone (for calling the bank).", color = Muted)
                OutlinedTextField(server, { server = it }, label = { Text("Bank server") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                error?.let { Banner(it, Tone.Danger) }
                Button({ submit() }, enabled = !busy, modifier = Modifier.fillMaxWidth().height(52.dp)) {
                    if (busy) CircularProgressIndicator(color = androidx.compose.ui.graphics.Color.White) else Text("Open my account", fontSize = 17.sp)
                }
            }
        }
        if (step > 0) TextButton({ step-- }) { Text("Back") }
        Spacer(Modifier.height(24.dp))
    }
}
