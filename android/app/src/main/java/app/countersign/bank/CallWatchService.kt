package app.countersign.bank

import android.Manifest
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.telephony.TelephonyCallback
import android.telephony.TelephonyManager
import app.countersign.bank.data.LiveCall
import app.countersign.bank.data.Member
import app.countersign.bank.data.RealRepository
import app.countersign.bank.data.Repo
import java.util.UUID

/**
 * Runs while the app is signed in. Two jobs:
 *
 * 1. Tells the engine when a call on this phone rings, goes out, is answered and ends
 *    (`/api/m/call-event`). Never the number or the audio: only which family member's number it
 *    was ([FamilyNumbers]), or nothing. A family member's number ringing starts a check at once.
 * 2. Keeps the app alive with RealRepository's events socket open, so family checks and
 *    approvals ring or notify at once.
 */
class CallWatchService : Service() {
    private val main = Handler(Looper.getMainLooper())
    private lateinit var phone: TelephonyManager
    private lateinit var audio: AudioManager
    private var phoneCallback: TelephonyCallback? = null
    private var modeListener: AudioManager.OnModeChangedListener? = null

    private var callState = TelephonyManager.CALL_STATE_IDLE

    /** The call going on now, as reported to the engine. */
    private class Current(val id: String, val kind: String, val incoming: Boolean, val peer: Member?, var answered: Boolean)

    private var current: Current? = null

    private val poll = object : Runnable {
        override fun run() {
            update() // some phones don't report every audio mode change
            main.postDelayed(this, 2000)
        }
    }
    private val real get() = Repo.instance as? RealRepository

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        phone = getSystemService(TelephonyManager::class.java)
        audio = getSystemService(AudioManager::class.java)
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(Notify.WATCH_ID, Notify.watch(this, false), ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(Notify.WATCH_ID, Notify.watch(this, false))
        }
        watchCalls()
        real?.connect()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        phoneCallback?.let { phone.unregisterTelephonyCallback(it) }
        modeListener?.let { audio.removeOnModeChangedListener(it) }
        real?.disconnect()
        super.onDestroy()
    }

    // ------------------------------------------------------------------ calls
    private inner class PhoneState : TelephonyCallback(), TelephonyCallback.CallStateListener {
        override fun onCallStateChanged(state: Int) {
            callState = state
            update()
        }
    }

    private fun watchCalls() {
        if (checkSelfPermission(Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED) {
            phoneCallback = PhoneState().also { phone.registerTelephonyCallback(mainExecutor, it) }
        }
        modeListener = AudioManager.OnModeChangedListener { update() }.also { audio.addOnModeChangedListener(mainExecutor, it) }
        main.post(poll)
    }

    private fun update() {
        val mode = audio.mode
        val internet = mode == AudioManager.MODE_IN_COMMUNICATION || (Build.VERSION.SDK_INT >= 33 && mode == AudioManager.MODE_COMMUNICATION_REDIRECT)
        val c = current
        when {
            BankCall.active -> {} // our own call to the bank isn't a caller pressuring you
            // without the phone permission, the ringtone audio mode still says a call is ringing
            callState == TelephonyManager.CALL_STATE_RINGING || (c == null && mode == AudioManager.MODE_RINGTONE) -> if (c == null) {
                start("ringing", "phone", incoming = true, peer = family(FamilyNumbers.takeIncoming()))
            }
            callState == TelephonyManager.CALL_STATE_OFFHOOK || mode == AudioManager.MODE_IN_CALL -> when {
                c == null -> start("outgoing", "phone", incoming = false, peer = family(FamilyNumbers.takeOutgoing()))
                c.incoming && !c.answered -> answered(c)
            }
            // WhatsApp-style calls: no ringing state and no number, so just "on a call" and "ended"
            internet -> if (c == null) start("answered", "internet", incoming = false, peer = null)
            c != null -> end(c)
        }
    }

    private fun family(number: String?): Member? = FamilyNumbers.match(number, Repo.instance.home.value?.family.orEmpty())

    private fun start(event: String, kind: String, incoming: Boolean, peer: Member?) {
        val c = Current(UUID.randomUUID().toString(), kind, incoming, peer, answered = event == "answered")
        current = c
        real?.callEvent(c.id, event, kind, peer)
        if (incoming && peer != null) real?.autoCheck(c.id, peer)
        real?.setCall(LiveCall(c.id, incoming, c.answered, peer, null))
        showOnCall(true)
    }

    private fun answered(c: Current) {
        c.answered = true
        real?.callEvent(c.id, "answered", c.kind, c.peer)
        real?.setCall(LiveCall(c.id, c.incoming, true, c.peer, null))
    }

    private fun end(c: Current) {
        current = null
        real?.callEvent(c.id, "ended", c.kind, c.peer)
        real?.setCall(null)
        showOnCall(false)
    }

    private fun showOnCall(onCall: Boolean) =
        getSystemService(android.app.NotificationManager::class.java).notify(Notify.WATCH_ID, Notify.watch(this, onCall))

    companion object {
        fun start(c: Context) {
            if (Prefs.signedIn) c.startForegroundService(Intent(c, CallWatchService::class.java))
        }

        fun stop(c: Context) = c.stopService(Intent(c, CallWatchService::class.java))
    }
}

/** Whether a screen of the app is in front (then the screen shows payment news itself). */
object App {
    @Volatile
    var visible = false
}
