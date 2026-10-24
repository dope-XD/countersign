package app.countersign.bank.ui

import android.content.Intent
import android.net.Uri
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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.fragment.app.FragmentActivity
import app.countersign.bank.Api
import app.countersign.bank.ApiError
import app.countersign.bank.Bus
import app.countersign.bank.FamilyOption
import app.countersign.bank.Payment
import kotlinx.coroutines.launch
import org.json.JSONObject

@Composable
fun PayForm(model: HomeModel, open: (Payment) -> Unit) {
    val scope = rememberCoroutineScope()
    var payee by remember { mutableStateOf("") }
    var amount by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    Column(Modifier.verticalScroll(rememberScrollState()).imePadding().padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("Pay by UPI", fontSize = 24.sp, fontWeight = FontWeight.Bold)
        OutlinedTextField(payee, { payee = it.trim() }, label = { Text("UPI ID") }, placeholder = { Text("name@bank") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(
            amount, { amount = it.filter { c -> c.isDigit() }.take(8) }, label = { Text("Amount") }, prefix = { Text("₹ ") }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(note, { note = it }, label = { Text("Note (optional)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        model.home?.family?.takeIf { it.isNotEmpty() }?.let { fam ->
            Text("Family", color = Muted)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                fam.forEach { f -> OutlinedButton({ payee = f.upi }) { Text(f.label) } }
            }
        }
        error?.let { Banner(it, Tone.Danger) }
        Button({
            busy = true
            error = null
            scope.launch {
                try {
                    val p = Payment.from(Api.post("/api/m/pay", JSONObject().put("payee", payee).put("amount", amount.toDouble()).put("note", note)))
                    payee = ""
                    amount = ""
                    note = ""
                    model.load()
                    open(p)
                } catch (e: ApiError) {
                    error = e.message
                } finally {
                    busy = false
                }
            }
        }, enabled = !busy && payee.contains('@') && (amount.toDoubleOrNull() ?: 0.0) > 0, modifier = Modifier.fillMaxWidth().height(54.dp)) {
            Text("Pay", fontSize = 18.sp)
        }
        Text(
            "Paying during a call, or to someone new? CS Bank may pause and help you check with family first. It never blocks you.",
            color = Muted, fontSize = 14.sp,
        )
    }
}

/** One payment from start to finish: the pause, the family check, the safe ways forward, the result. */
@Composable
fun PaymentSheet(activity: FragmentActivity, start: Payment, model: HomeModel, close: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var p by remember { mutableStateOf(start) }
    var message by remember { mutableStateOf<Pair<String, Tone>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }

    LaunchedEffect(start.id) {
        Bus.events.collect { e ->
            if (e.optString("type") == "payment") {
                val np = Payment.from(e.getJSONObject("payment"))
                if (np.id == p.id) {
                    p = np
                    e.optString("message").takeIf { it.isNotEmpty() }?.let { message = it to toneOf(e.optString("tone")) }
                }
            }
        }
    }
    LaunchedEffect(start.id) { // also poll, in case an event was missed
        while (true) {
            kotlinx.coroutines.delay(5000)
            runCatching { p = Payment.from(Api.get("/api/m/payments/${p.id}")) }
        }
    }

    fun act(path: String, body: JSONObject = JSONObject()) {
        busy = true
        error = null
        scope.launch {
            try {
                p = Payment.from(Api.post("/api/m/payments/${p.id}/$path", body))
                model.load()
            } catch (e: ApiError) {
                error = e.message
            } finally {
                busy = false
            }
        }
    }

    Column(
        Modifier.fillMaxSize().systemBarsPadding().verticalScroll(rememberScrollState()).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text("${p.amountText} to ${p.payee}", fontWeight = FontWeight.Bold, fontSize = 18.sp, modifier = Modifier.weight(1f))
            TextButton(close) { Text("Close") }
        }
        message?.takeIf { p.report == null }?.let { (m, t) -> Banner(m, t) } // a stopped scam has its own red screen
        error?.let { Banner(it, Tone.Danger) }
        when (p.status) {
            "executed" -> Done(p)
            "cancelled" -> Stopped(p)
            "confirm" -> {
                Text("Did someone ask you for this money?", fontSize = 24.sp, fontWeight = FontWeight.Bold)
                Text("On a call, by WhatsApp, or by message. Scammers pretend to be family, police or the bank.", color = Muted)
                Button({ act("asked", JSONObject().put("someone_asked", true)) }, enabled = !busy, modifier = Modifier.fillMaxWidth().height(52.dp)) {
                    Text("Yes, someone asked me")
                }
                OutlinedButton({ act("asked", JSONObject().put("someone_asked", false)) }, enabled = !busy, modifier = Modifier.fillMaxWidth().height(52.dp)) {
                    Text("No, this is my own payment")
                }
            }
            else -> Paused(p, busy, ::act, ctx)
        }
        Spacer(Modifier.height(30.dp))
    }
}

@Composable
private fun Paused(p: Payment, busy: Boolean, act: (String, JSONObject) -> Unit, ctx: android.content.Context) {
    val held = p.status == "held"
    if (held) {
        Banner("The money is set aside and leaves at ${clockAt(p.holdUntil ?: 0.0)}. You, or family saying \"No\", can still stop it.", Tone.Warn, title = "On hold for an hour")
    } else {
        Text(
            if (p.reasons.firstOrNull()?.startsWith("Someone asked") == true) "Check before you send" else "Wait. Is someone on this call asking for this money?",
            fontSize = 23.sp, fontWeight = FontWeight.Bold,
        )
        p.reasons.forEach { Text("•  $it", color = Ink) }
        p.tips.forEach { Banner(it, Tone.Danger) }
    }

    Section("Check with family") {
        if (p.family.isEmpty()) {
            Text("Add family in the Family tab, and they can confirm requests like this for you.", color = Muted)
        }
        p.family.forEach { f -> FamilyRow(f, busy) { act("ask/${f.id}", JSONObject()) } }
        if (p.family.size > 1 && p.family.any { it.answer == null }) {
            OutlinedButton({ act("ask-all", JSONObject()) }, enabled = !busy, modifier = Modifier.fillMaxWidth()) { Text("Ask everyone at once") }
        }
    }

    if (p.family.isNotEmpty() && !held) {
        Section("They say their phone is broken, or they're on a friend's phone?") {
            Text("That's what scammers say, and sometimes it's true. These help the real person and never a scammer:", color = Muted)
            p.family.forEach { f ->
                Button({ act("redirect/${f.id}", JSONObject()) }, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
                    Text("Send it to ${f.label}'s own account instead")
                }
                OutlinedButton({ ctx.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${f.mobile}"))) }, modifier = Modifier.fillMaxWidth()) {
                    Text("Call ${f.label} on their own number")
                }
                if (f.simSwapped) Banner("${f.label}'s SIM was changed recently, so their number may not reach them.", Tone.Warn)
            }
            Text("If the caller refuses and insists on another account, that's the warning sign.", color = Red, fontWeight = FontWeight.SemiBold)
        }
    }

    HorizontalDivider()
    if (!held) {
        OutlinedButton({ act("hold", JSONObject()) }, enabled = !busy, modifier = Modifier.fillMaxWidth().height(50.dp)) {
            Text(if (p.amount >= 10_000) "Send anyway, with a 1-hour hold" else "Send anyway")
        }
    }
    Button(
        { act("cancel", JSONObject()) }, enabled = !busy, modifier = Modifier.fillMaxWidth().height(50.dp),
        colors = ButtonDefaults.buttonColors(containerColor = Red),
    ) { Text("Cancel the payment") }
}

@Composable
private fun FamilyRow(f: FamilyOption, busy: Boolean, ask: () -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Face(f.label)
        Column(Modifier.weight(1f)) {
            Text(f.label, fontWeight = FontWeight.Bold)
            val s = f.status
            when {
                s == null -> {}
                !s.shared -> Text("Doesn't share call status", color = Muted, fontSize = 13.sp)
                s.onCall == true -> Text("${f.label}'s phone is on a call right now", color = Amber, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                else -> Text("${f.label}'s phone isn't on any call right now", color = Red, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            }
            when (f.answer) {
                "pending" -> Text(if (f.newLink) "Asking… (new family link: can stop, not release at once)" else "Asking… waiting for an answer", color = Brand, fontSize = 13.sp)
                "approved" -> Text("Said yes, it was them", color = Green, fontSize = 13.sp)
                "declined" -> Text("Said NO, it wasn't them", color = Red, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                "expired" -> Text("Didn't answer", color = Muted, fontSize = 13.sp)
            }
        }
        if (f.answer == null || f.answer == "expired") Button(ask, enabled = !busy) { Text("Ask") }
    }
}

@Composable
private fun Done(p: Payment) {
    val r = p.redirectedTo
    if (r != null) {
        Banner("${p.amountText} went to ${r.optString("label")}'s own account (${r.optString("upi_id")}) instead of ${r.optString("instead_of")}.", Tone.Ok, title = "Sent to family")
    } else {
        Banner("${p.amountText} sent to ${p.payee}.", Tone.Ok, title = "Payment sent")
    }
}

@Composable
private fun Stopped(p: Payment) {
    val report = p.report
    if (report != null) {
        Banner("We stopped the payment. Hang up now, and don't send money to anyone on that call.", Tone.Danger, title = "Your family member says it isn't them")
        Section("Report it: 1930") {
            Text("Call 1930, the national cyber fraud helpline, or report at cybercrime.gov.in. We've filled in the details for you:", color = Muted)
            KeyValue("Category", "Impersonation (possible AI voice)")
            KeyValue("Amount asked", p.amountText)
            KeyValue("Payee", p.payee)
            Text("Case ${p.caseId ?: ""} is with our fraud team.", color = Muted, fontSize = 13.sp)
        }
    } else {
        Banner("Nothing was sent.", Tone.Info, title = "Payment cancelled")
    }
}
