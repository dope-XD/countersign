package app.countersign.bank

import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.util.Log
import app.countersign.bank.data.RealRepository
import app.countersign.bank.data.Repo
import app.countersign.bank.data.listen.LEVELS
import app.countersign.bank.data.listen.Verdict
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONArray
import org.json.JSONObject

/**
 * The stronger check (CONTRACT.md, "Call listener"): while a call is being listened to and the
 * user has "stronger check" on, the call's audio goes to the bank's own server over `/ws/listen`,
 * and the server's `listen_verdict` goes into [CallRisk]. Nothing is stored, here or there.
 *
 * If the socket drops it reconnects with a growing pause, and meanwhile the phone carries on alone.
 * If the server says the stronger check is off for this account (4403), it stops for the call.
 */
object ListenStream {
    private const val TAG = "ListenStream"

    /** 100 ms of 16 kHz audio per message, within the contract's 20–200 ms. */
    private const val SAMPLES_PER_MESSAGE = ListenService.RATE / 10
    private const val OFF_FOR_ACCOUNT = 4403
    private const val SERVER_BUSY = 1013

    // lazy: parseVerdict runs in plain JVM tests, where there is no main thread
    private val scope by lazy { CoroutineScope(SupervisorJob() + Dispatchers.Main) }
    private val main by lazy { Handler(Looper.getMainLooper()) }
    private val jobs = mutableListOf<Job>()
    private var streaming: Job? = null
    private var socket: WebSocket? = null
    private var callId: String? = null
    private var retries = 0
    private var refusedFor: String? = null
    private var lastContext: String? = null

    fun start() {
        if (jobs.isNotEmpty()) return
        val repo = Repo.instance
        jobs += scope.launch {
            combine(repo.call, repo.home, ListenService.recording) { call, home, recording ->
                call?.id?.takeIf { recording && home?.me?.strongerCheck != false }
            }.distinctUntilChanged().collect { id ->
                if (id != null) connect(id) else disconnect()
            }
        }
    }

    fun stop() {
        jobs.forEach { it.cancel() }
        jobs.clear()
        disconnect()
    }

    /** A `listen_verdict` message, or null for anything else (or when the server abstains). */
    fun parseVerdict(text: String): Verdict? {
        val o = runCatching { JSONObject(text) }.getOrNull() ?: return null
        if (o.optString("type") != "listen_verdict" || o.optBoolean("abstain")) return null
        val level = o.optString("level").takeIf { it in LEVELS } ?: return null
        val cues = o.optJSONArray("cues")?.let { a -> (0 until a.length()).map { a.getString(it) } }.orEmpty()
        return Verdict(level, o.optString("scam_type", "unknown"), cues, emptyList())
    }

    private fun connect(id: String) {
        if (callId != id) {
            callId = id
            retries = 0
            lastContext = null
        }
        if (socket != null || refusedFor == id) return
        val token = Prefs.token ?: return
        val lang = Repo.instance.home.value?.me?.lang?.code ?: "en"
        val url = Prefs.server.replaceFirst(Regex("^http"), "ws") + "/ws/listen?call_id=" + Uri.encode(id) +
            "&lang=$lang&token=" + Uri.encode(token)
        Log.i(TAG, "connecting for call $id")
        socket = Api.http.newWebSocket(Api.request("").url(url).build(), Listener(id))
    }

    private fun disconnect() {
        callId = null
        streaming?.cancel()
        streaming = null
        socket?.close(1000, "call ended")
        socket = null
        main.removeCallbacksAndMessages(null)
        ready(false)
    }

    /** While the socket is up, something is making sense of the audio: the listener can say LISTENING. */
    private fun ready(on: Boolean) {
        (Repo.instance as? RealRepository)?.analysisReady = on
    }

    /** Tells the server what the phone sees ([CallContext]), if it's listening and anything changed. */
    fun sendContext() {
        val s = socket ?: return
        val call = Repo.instance.call.value ?: return
        val msg = JSONObject().put("type", "context").put("signals", JSONArray(CallRisk.signals.sorted()))
            .put("caller_check", call.check?.verdict?.wire ?: JSONObject.NULL).toString()
        if (msg != lastContext && s.send(msg)) lastContext = msg
    }

    private fun stream(s: WebSocket) {
        streaming?.cancel()
        streaming = scope.launch(Dispatchers.Default) {
            val chunks = PcmChunks(SAMPLES_PER_MESSAGE)
            ListenService.audio.collect { frame -> chunks.add(frame) { s.send(it.toByteString()) } }
        }
    }

    private class Listener(private val id: String) : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) = post {
            if (socket !== webSocket) return@post
            Log.i(TAG, "streaming the call")
            retries = 0
            lastContext = null // a new socket knows nothing yet: send the context again
            ready(true)
            stream(webSocket)
            sendContext()
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val v = parseVerdict(text) ?: return
            post { if (callId == id) CallRisk.update { server(v) } }
        }

        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {}

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(1000, null)
            post { dropped(webSocket, code) }
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = post {
            Log.w(TAG, "socket dropped: $t")
            dropped(webSocket, response?.code ?: 0)
        }

        private fun dropped(webSocket: WebSocket, code: Int) {
            if (socket !== webSocket) return
            socket = null
            streaming?.cancel()
            streaming = null
            ready(false) // the phone carries on alone meanwhile
            if (callId != id) return
            if (code == OFF_FOR_ACCOUNT) {
                Log.i(TAG, "stronger check is off for this account")
                refusedFor = id
                return
            }
            val wait = if (code == SERVER_BUSY) 15_000L else minOf(30_000L, 1000L shl minOf(retries++, 5))
            main.postDelayed({ if (callId == id) connect(id) }, wait)
        }

        private fun post(block: () -> Unit) {
            main.post(block)
        }
    }
}

/** Packs 20 ms frames into fixed-size chunks of little-endian 16-bit PCM, as `/ws/listen` takes them. */
class PcmChunks(samplesPerChunk: Int) {
    private val buf = ByteArray(samplesPerChunk * 2)
    private var pos = 0

    fun add(frame: ShortArray, emit: (ByteArray) -> Unit) {
        for (x in frame) {
            buf[pos++] = (x.toInt() and 0xff).toByte()
            buf[pos++] = (x.toInt() shr 8 and 0xff).toByte()
            if (pos == buf.size) {
                emit(buf.copyOf())
                pos = 0
            }
        }
    }
}
