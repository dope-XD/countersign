package app.countersign.bank.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.countersign.bank.Api
import app.countersign.bank.ApiError
import app.countersign.bank.CallWatchService
import app.countersign.bank.DeviceKey
import app.countersign.bank.Prefs
import kotlinx.coroutines.launch
import org.json.JSONObject

@Composable
fun ProfileScreen(model: HomeModel, signOut: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val a = model.home?.account ?: return
    var error by remember { mutableStateOf<String?>(null) }

    fun save(body: JSONObject) {
        scope.launch {
            try {
                Api.post("/api/m/prefs", body)
            } catch (e: ApiError) {
                error = e.message
            }
            model.load()
        }
    }

    Column(Modifier.verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text(a.name, fontSize = 24.sp, fontWeight = FontWeight.Bold)
        Section("Account") {
            KeyValue("Mobile", a.mobile)
            KeyValue("Account", a.accountNo)
            KeyValue("UPI ID", a.upi)
            KeyValue("Debit card", "•••• ${a.card4}")
            Text("When you call CS Bank, the agent may ask for your card's last four digits.", color = Muted, fontSize = 13.sp)
        }
        Section("Family checks reach me by") {
            listOf("ring" to "Ringing, like a call", "notify" to "A notification").forEach { (v, label) ->
                Row(Modifier.fillMaxWidth().selectable(a.channel == v) { save(JSONObject().put("check_channel", v)) }, verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(a.channel == v, { save(JSONObject().put("check_channel", v)) })
                    Text(label)
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Tell family whether I'm on a call", fontWeight = FontWeight.SemiBold)
                    Text("Only yes or no, only while they're checking with you.", color = Muted, fontSize = 13.sp)
                }
                Switch(a.shareCallStatus, { save(JSONObject().put("share_call_status", it)) })
            }
        }
        Section("This phone") {
            Text("Approvals are signed by a key in this phone's secure hardware, unlocked by your fingerprint or screen lock.", color = Muted, fontSize = 14.sp)
            KeyValue("Bank server", Prefs.server.removePrefix("https://"))
            OutlinedButton({
                CallWatchService.stop(ctx)
                DeviceKey.delete()
                signOut()
            }, Modifier.fillMaxWidth()) { Text("Sign out of this phone") }
        }
        error?.let { Banner(it, Tone.Danger) }
    }
}
