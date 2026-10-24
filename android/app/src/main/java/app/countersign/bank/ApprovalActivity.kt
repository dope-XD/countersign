package app.countersign.bank

import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.view.WindowManager
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.fragment.app.FragmentActivity
import app.countersign.bank.ui.Banner
import app.countersign.bank.ui.CsTheme
import app.countersign.bank.ui.Green
import app.countersign.bank.ui.Red
import app.countersign.bank.ui.Tone
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.Locale

/**
 * A family check or bank approval, full screen and over the lock screen. Set to "ring", it rings
 * like an incoming call until answered, then reads the question aloud. The screen can't be
 * captured or shared (FLAG_SECURE), so a remote-access app can't watch someone approve.
 */
class ApprovalActivity : FragmentActivity() {
    private var tts: TextToSpeech? = null
    private var approval by mutableStateOf<Approval?>(null)
    private var answered by mutableStateOf(false)
    private var done by mutableStateOf<String?>(null)
    private var error by mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE or WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        load(intent)
        setContent { CsTheme { Screen() } }
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        load(intent)
    }

    private fun load(i: android.content.Intent) {
        answered = false
        done = null
        error = null
        i.getStringExtra(EXTRA)?.let { show(Approval.from(JSONObject(it))) }
        i.getStringExtra(EXTRA_ID)?.let { id ->
            rememberLoad(id)
        }
    }

    private fun rememberLoad(id: String) {
        kotlinx.coroutines.MainScope().launch {
            val a = Approvals.load(id)
            if (a == null) done = "This request has already been answered or has expired." else show(a)
        }
    }

    private fun show(a: Approval) {
        approval = a
        if (a.deliver == "ring" && intent.getStringExtra(EXTRA) != null) {
            Ringer.start(this) // keeps ringing until "Answer"
        } else {
            answer()
        }
    }

    private fun answer() {
        Ringer.stop()
        answered = true
        val a = approval ?: return
        tts = TextToSpeech(this) { ok ->
            if (ok == TextToSpeech.SUCCESS) {
                tts?.language = Locale.forLanguageTag("en-IN")
                val intro = if (a.isFamily) "Family check from CS Bank. " else "CS Bank. "
                tts?.speak(intro + a.question + " " + a.detail, TextToSpeech.QUEUE_FLUSH, null, a.id)
            }
        }
    }

    override fun onDestroy() {
        Ringer.stop()
        tts?.shutdown()
        super.onDestroy()
    }

    @androidx.compose.runtime.Composable
    private fun Screen() {
        val scope = rememberCoroutineScope()
        val a = approval
        Column(
            Modifier.fillMaxSize().background(Color(0xFF0E1A26)).systemBarsPadding().padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            Spacer(Modifier.height(24.dp))
            val d = done
            if (d != null || a == null) {
                Text(d ?: "Loading…", color = Color.White, fontSize = 22.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
                Button({ finish() }, Modifier.fillMaxWidth().height(56.dp)) { Text("Close") }
                return@Column
            }
            Text(
                when {
                    a.isFamily -> "FAMILY CHECK · CS BANK"
                    a.kind == "kill_switch_off" -> "KILL SWITCH · CS BANK"
                    else -> "CS BANK · APPROVAL"
                },
                color = Color(0xFF8DB8E8), fontWeight = FontWeight.Bold, fontSize = 14.sp,
            )
            Text(a.question, color = Color.White, fontSize = 30.sp, fontWeight = FontWeight.ExtraBold)
            if (!answered) {
                Text("Someone needs your answer now.", color = Color(0xFFB8C7D4), fontSize = 18.sp)
                Spacer(Modifier.weight(1f))
                Button({ answer() }, Modifier.fillMaxWidth().height(64.dp), colors = ButtonDefaults.buttonColors(containerColor = Green)) {
                    Text("Answer", fontSize = 20.sp)
                }
                return@Column
            }
            Text(a.detail, color = Color(0xFFD4DEE8), fontSize = 18.sp)
            if (a.isFamily) {
                Banner("If someone on a call asked you to press Yes, press No.", Tone.Warn)
            }
            error?.let { Banner(it, Tone.Danger) }
            Spacer(Modifier.weight(1f))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button({
                    scope.launch {
                        error = Approvals.decide(this@ApprovalActivity, a, approve = false)
                        if (error == null) done = if (a.isFamily) "Thanks. We've stopped the payment and told them it wasn't you." else "Thanks. Nothing was changed."
                    }
                }, Modifier.weight(1f).height(64.dp), colors = ButtonDefaults.buttonColors(containerColor = Red)) {
                    Text(if (a.isFamily) "No, not me" else "No", fontSize = 18.sp)
                }
                Button({
                    scope.launch {
                        error = Approvals.decide(this@ApprovalActivity, a, approve = true)
                        if (error == null) done = "Confirmed. Thank you."
                    }
                }, Modifier.weight(1f).height(64.dp), colors = ButtonDefaults.buttonColors(containerColor = Green)) {
                    Text(if (a.isFamily) "Yes, it was me" else "Yes", fontSize = 18.sp)
                }
            }
        }
    }

    companion object {
        const val EXTRA = "approval" // the approval JSON, from a notification
        const val EXTRA_ID = "approval_id" // or just its id, from inside the app
    }
}
