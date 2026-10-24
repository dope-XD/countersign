package app.countersign.bank

import android.Manifest
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.content.pm.PackageManager
import android.telephony.SmsManager
import android.util.Log
import app.countersign.bank.data.RealRepository
import app.countersign.bank.data.Repo
import app.countersign.bank.data.RiskLevel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/**
 * When a call first reaches `scam` (from the listener, or the user pressing "Alert family"):
 * `POST /api/m/scam-alert` once, which turns on the pay guard and alarms the family's apps, then
 * texts from this phone's SIM the members whose app is offline (`text_these`), or every member if
 * the alert couldn't be sent. Each member is texted at most once per call, and only with
 * "Text family" (`sms_fallback`) on and the SMS permission granted.
 */
object ScamAlert {
    private const val TAG = "ScamAlert"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var watching: Job? = null
    private var alertedCall: String? = null
    private val texted = mutableSetOf<String>()

    fun start(c: Context) {
        if (watching != null) return
        val app = c.applicationContext
        val repo = Repo.instance as? RealRepository ?: return
        watching = scope.launch {
            repo.call.map { call -> call?.takeIf { it.risk?.level == RiskLevel.SCAM } }
                .distinctUntilChanged { a, b -> a?.id == b?.id }
                .collect { call -> if (call != null && call.id != alertedCall) alert(app, repo, call.id) }
        }
    }

    fun stop() {
        watching?.cancel()
        watching = null
    }

    private suspend fun alert(app: Context, repo: RealRepository, callId: String) {
        alertedCall = callId
        texted.clear()
        val risk = repo.call.value?.takeIf { it.id == callId }?.risk ?: return
        Log.i(TAG, "scam call: alerting family (${risk.type}, ${risk.sources})")
        val family = repo.home.value?.family.orEmpty()
        val toText = try {
            val ids = repo.scamAlert(callId, risk).toSet()
            Log.i(TAG, "alert sent; ${ids.size} to text, ${family.size} in the family")
            family.filter { it.id in ids }
        } catch (e: Exception) {
            Log.w(TAG, "alert not sent (${e.message}): texting everyone")
            family
        }
        text(app, repo, toText.map { it.id to it.mobile })
        escalate(app, repo, callId)
    }

    /**
     * Nobody may miss this: if no family member acts on the alarm (Call / Message / OK) within [ACK_WAIT_MS], text all of
     * them, and call the first one from this phone, so a real person comes on the line. Stops the moment one acts.
     */
    private fun escalate(app: Context, repo: RealRepository, callId: String) {
        escalation?.cancel()
        escalation = scope.launch {
            val acked = kotlinx.coroutines.withTimeoutOrNull(ACK_WAIT_MS) { repo.alarmAcks.first() }
            if (acked != null || alertedCall != callId || repo.call.value?.cleared == true) {
                Log.i(TAG, "family acknowledged the alarm")
                return@launch
            }
            val family = repo.home.value?.family.orEmpty()
            Log.w(TAG, "nobody acknowledged the alarm in ${ACK_WAIT_MS / 1000} s: texting and calling")
            text(app, repo, family.map { it.id to it.mobile })
            val first = family.firstOrNull { it.online } ?: family.firstOrNull() ?: return@launch
            if (app.checkSelfPermission(Manifest.permission.CALL_PHONE) != PackageManager.PERMISSION_GRANTED) {
                Log.w(TAG, "no call permission: can't call family")
                return@launch
            }
            Notify.news(app, app.getString(R.string.sms_scam_alarm_unanswered, first.label), "")
            runCatching {
                app.startActivity(Intent(Intent.ACTION_CALL, Uri.parse("tel:${first.mobile}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }.onFailure { Log.w(TAG, "call not placed: $it") }
        }
    }

    private const val ACK_WAIT_MS = 60_000L
    private var escalation: Job? = null

    private fun text(app: Context, repo: RealRepository, members: List<Pair<String, String>>) {
        if (members.isEmpty()) {
            Log.i(TAG, "nobody to text")
            return
        }
        val me = repo.home.value?.me
        if (me?.smsFallback == false) {
            Log.i(TAG, "\"text family\" is off: ${members.size} not texted")
            return
        }
        if (app.checkSelfPermission(Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) {
            Log.w(TAG, "no SMS permission: family not texted")
            return
        }
        val body = app.getString(R.string.sms_scam_alert, me?.name?.substringBefore(' ').orEmpty())
        val sms = app.getSystemService(SmsManager::class.java)
        for ((id, mobile) in members) {
            if (!texted.add(id)) continue
            runCatching { sms.sendMultipartTextMessage(mobile, null, sms.divideMessage(body), null, null) }
                .onSuccess { Log.i(TAG, "texted a family member") } // never log the number
                .onFailure { Log.w(TAG, "text not sent: $it") }
        }
    }
}
