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
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject

/**
 * Runs while the app is signed in. Two jobs:
 *
 * 1. Tells the bank when this phone is on a call, and whether the call came in or went out.
 *    Only the fact of the call: never the number, never the audio. The payment guard uses it, and
 *    family members see "on a call: yes/no" only while they are checking with you (if you share).
 * 2. Keeps a websocket to the bank open, so family checks and approvals ring or notify at once.
 */
class CallWatchService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val main = Handler(Looper.getMainLooper())
    private lateinit var phone: TelephonyManager
    private lateinit var audio: AudioManager
    private var phoneCallback: TelephonyCallback? = null
    private var modeListener: AudioManager.OnModeChangedListener? = null

    private var callState = TelephonyManager.CALL_STATE_IDLE
    private var rangFirst = false // RINGING before OFFHOOK: someone called us
    private var onCall = false
    private var kind = "phone"

    private var events: WebSocket? = null
    private var retries = 0
    private var stopped = false

    private val poll = object : Runnable {
        override fun run() {
            update() // some phones don't report every audio mode change
            main.postDelayed(this, 2000)
        }
    }
    private val heartbeat = object : Runnable {
        override fun run() {
            events?.send("hb") // tells the bank the app is alive ("Rahul's app was online 5 s ago")
            main.postDelayed(this, 20_000)
        }
    }

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
        connect()
        main.postDelayed(heartbeat, 20_000)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onDestroy() {
        stopped = true
        main.removeCallbacksAndMessages(null)
        phoneCallback?.let { phone.unregisterTelephonyCallback(it) }
        modeListener?.let { audio.removeOnModeChangedListener(it) }
        events?.close(1000, "bye")
        scope.cancel()
        super.onDestroy()
    }

    // ------------------------------------------------------------------ calls
    private inner class PhoneState : TelephonyCallback(), TelephonyCallback.CallStateListener {
        override fun onCallStateChanged(state: Int) {
            if (state == TelephonyManager.CALL_STATE_RINGING) rangFirst = true
            if (state == TelephonyManager.CALL_STATE_IDLE) rangFirst = false
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
        val normal = callState == TelephonyManager.CALL_STATE_OFFHOOK || mode == AudioManager.MODE_IN_CALL
        val internet = mode == AudioManager.MODE_IN_COMMUNICATION || (Build.VERSION.SDK_INT >= 33 && mode == AudioManager.MODE_COMMUNICATION_REDIRECT)
        val now = (normal || internet) && !BankCall.active // our own call to the bank isn't "a caller pressuring you"
        if (now == onCall) return
        onCall = now
        if (now) kind = if (normal) "phone" else "internet"
        val direction = when {
            kind == "internet" -> "unknown"
            rangFirst -> "incoming"
            else -> "outgoing"
        }
        report(if (now) "active" else "ended", kind, direction)
        getSystemService(android.app.NotificationManager::class.java).notify(Notify.WATCH_ID, Notify.watch(this, now))
    }

    private fun report(state: String, kind: String, direction: String) {
        scope.launch {
            try {
                Api.post("/api/m/call-state", JSONObject().put("state", state).put("kind", kind).put("direction", direction))
            } catch (e: ApiError) {
                Log.w(TAG, "call state not sent: ${e.message}")
            }
        }
    }

    // ------------------------------------------------------------------ bank events
    private fun connect() {
        val cid = Prefs.customerId
        if (stopped || cid == null) return
        val url = Prefs.server.replaceFirst(Regex("^http"), "ws") + "/ws/events?topics=app:$cid"
        events = Api.http.newWebSocket(Api.request("").url(url).build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                retries = 0
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                main.post { onEvent(text) }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.w(TAG, "events dropped: $t")
                reconnect()
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = reconnect()
        })
    }

    private fun reconnect() {
        if (stopped) return
        val delay = minOf(30_000L, 1000L shl minOf(retries++, 5))
        main.postDelayed({ connect() }, delay)
    }

    private fun onEvent(text: String) {
        val e = try {
            JSONObject(text)
        } catch (x: Exception) {
            return
        }
        Bus.events.tryEmit(e)
        when (e.optString("type")) {
            "approval" -> Notify.approval(this, e.getJSONObject("approval"))
            "alert" -> Notify.news(this, e.optString("title"), e.optString("body"))
            "family_request" -> Notify.news(this, "${e.optString("name")} wants to join your family", "Open CS Bank to confirm. Only accept people you know in person.")
            "family_joined" -> Notify.news(this, "You're now family with ${e.optString("name")}", "They can check with you before paying under pressure, and you with them.")
            "payment" -> if (!App.visible && e.optString("message").isNotEmpty()) {
                Notify.news(this, "Payment ${e.getJSONObject("payment").optString("amount_text")}", e.optString("message"))
            }
        }
    }

    companion object {
        private const val TAG = "CallWatch"

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
