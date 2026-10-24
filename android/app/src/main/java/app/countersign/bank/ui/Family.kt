package app.countersign.bank.ui

import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.countersign.bank.Api
import app.countersign.bank.ApiError
import app.countersign.bank.JoinRequest
import app.countersign.bank.MainActivity
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import com.google.zxing.BarcodeFormat
import com.google.zxing.qrcode.QRCodeWriter
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Family: people who can confirm "was it really me asking?" for each other. Joining takes both phones. */
@Composable
fun FamilyScreen(activity: MainActivity, model: HomeModel) {
    val scope = rememberCoroutineScope()
    val h = model.home
    var invite by remember { mutableStateOf<JSONObject?>(null) }
    var code by remember { mutableStateOf(activity.inviteCode ?: "") }
    var label by remember { mutableStateOf("") }
    var info by remember { mutableStateOf<Pair<String, Tone>?>(null) }
    var confirming by remember { mutableStateOf<JoinRequest?>(null) }
    var confirmLabel by remember { mutableStateOf("") }

    LaunchedEffect(activity.inviteCode) { activity.inviteCode?.let { code = it } }

    fun run(block: suspend () -> Unit) {
        scope.launch {
            try {
                block()
            } catch (e: ApiError) {
                info = (e.message ?: "Something went wrong") to Tone.Danger
            }
            model.load()
        }
    }

    Column(Modifier.verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("Family", fontSize = 24.sp, fontWeight = FontWeight.Bold)
        Text(
            "If someone calls one of you pretending to be another and asks for money, CS Bank asks the real person's phone first. " +
                "Family never see each other's balance.",
            color = Muted,
        )
        info?.let { (m, t) -> Banner(m, t) }

        h?.joinRequests?.forEach { j ->
            Section("${j.name} wants to join your family") {
                if (confirming == j) {
                    OutlinedTextField(confirmLabel, { confirmLabel = it }, label = { Text("What do you call ${j.name.substringBefore(' ')}?") }, placeholder = { Text("e.g. Rahul, Mom") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                    Button({
                        run {
                            Api.post("/api/m/family/confirm", JSONObject().put("customer_id", j.customerId).put("label", confirmLabel.trim()))
                            info = "${j.name} is now in your family." to Tone.Ok
                            confirming = null
                        }
                    }, enabled = confirmLabel.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text("Confirm") }
                } else {
                    Text("Only accept people you know in person. A family link made today can stop a payment but can't release money for 24 hours.", color = Muted)
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        OutlinedButton({ run { Api.post("/api/m/family/decline/${j.customerId}") } }, Modifier.weight(1f)) { Text("Decline") }
                        Button({
                            confirming = j
                            confirmLabel = j.name.substringBefore(' ')
                        }, Modifier.weight(1f)) { Text("Accept") }
                    }
                }
            }
        }

        Section("Your family") {
            val fam = h?.family.orEmpty()
            if (fam.isEmpty()) Text("No one yet. Add the person next to you.", color = Muted)
            fam.forEach { f ->
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Face(f.label)
                    Column(Modifier.weight(1f)) {
                        Text(f.label, fontWeight = FontWeight.Bold)
                        Text("${f.name} · ${f.mobile}", color = Muted, fontSize = 13.sp)
                    }
                    TextButton({ run { Api.delete("/api/m/family/${f.id}") } }) { Text("Remove") }
                }
            }
        }

        Section("Add family: show your code") {
            val inv = invite
            if (inv == null) {
                Button({ run { invite = Api.post("/api/m/family/invite") } }, Modifier.fillMaxWidth()) { Text("Show my family code") }
            } else {
                Text("Let them scan this in CS Bank, or type the code. It lasts 10 minutes.", color = Muted)
                QrImage(inv.getString("qr"))
                Text(inv.getString("code").chunked(3).joinToString(" "), fontSize = 34.sp, fontWeight = FontWeight.ExtraBold, color = Brand)
                Text("You'll confirm them here once they join.", color = Muted, fontSize = 13.sp)
            }
        }

        Section("Join someone's family") {
            OutlinedButton({
                val opts = GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build()
                GmsBarcodeScanning.getClient(activity, opts).startScan().addOnSuccessListener { b ->
                    Regex("\\d{6}").find(b.rawValue.orEmpty())?.let { code = it.value }
                }
            }, Modifier.fillMaxWidth()) { Text("Scan their code") }
            OutlinedTextField(
                code, { code = it.filter { c -> c.isDigit() }.take(6) }, label = { Text("Or type the 6-digit code") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(label, { label = it }, label = { Text("What do you call them?") }, placeholder = { Text("e.g. Mom, Rahul") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Button({
                run {
                    val r = Api.post("/api/m/family/join", JSONObject().put("code", code).put("label", label.trim()))
                    info = "Asked to join. ${r.optString("inviter")} needs to confirm on their phone." to Tone.Info
                    code = ""
                    label = ""
                    activity.inviteCode = null
                }
            }, enabled = code.length == 6 && label.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text("Join") }
        }
    }
}

@Composable
fun QrImage(text: String) {
    val bmp = remember(text) {
        val m = QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, 512, 512)
        val b = Bitmap.createBitmap(m.width, m.height, Bitmap.Config.RGB_565)
        for (x in 0 until m.width) for (y in 0 until m.height) b.setPixel(x, y, if (m[x, y]) android.graphics.Color.BLACK else android.graphics.Color.WHITE)
        b.asImageBitmap()
    }
    Image(bmp, "Family code", Modifier.size(220.dp))
}
