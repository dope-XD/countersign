package app.countersign.bank

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.os.SystemClock
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import kotlinx.coroutines.flow.MutableSharedFlow
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.net.URLEncoder
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Locale
import java.util.concurrent.LinkedBlockingQueue
import kotlin.concurrent.thread
import kotlin.math.abs
import kotlin.math.min

/**
 * A voice call to the bank from inside the app, like a bank app's "Call us" button. Audio goes
 * out exactly as a phone line carries it: 8 kHz G.711 mu-law in 20 ms frames over /ws/caller
 * (the same wire format as web/public/worklets/capture.js). The mic uses Android's voice-call
 * path with hardware echo cancellation, so the agent's voice from the speaker isn't sent back.
 *
 * Attack mode plays a voice clip into the call instead of the mic, from a claimed number:
 * exactly what a fraudster with a cloned voice does.
 */
object BankCall {
    @Volatile
    var active = false
        private set

    /** Everything the call screen shows: the bank's messages plus local ones ("local_state"). */
    val events = MutableSharedFlow<JSONObject>(extraBufferCapacity = 128)

    private const val RATE = 8000
    private const val FRAME = 160 // 20 ms
    private var ws: WebSocket? = null
    private var record: AudioRecord? = null
    private var track: AudioTrack? = null
    private var tts: TextToSpeech? = null
    private var micMuted = false // while the phone itself reads an agent line aloud
    @Volatile
    private var agentPlayingUntil = 0L // half duplex: the mic sends silence while the bank's voice plays
    private var userMuted = false
    private val playQueue = LinkedBlockingQueue<ShortArray>()
    private lateinit var appContext: Context

    fun start(c: Context, cli: String, lang: String, clip: ShortArray?) {
        if (active) return
        appContext = c.applicationContext
        active = true
        userMuted = false
        micMuted = false
        playQueue.clear()
        val am = appContext.getSystemService(AudioManager::class.java)
        am.mode = AudioManager.MODE_IN_COMMUNICATION
        speaker(true)
        tts = TextToSpeech(appContext) { ok ->
            if (ok == TextToSpeech.SUCCESS) {
                tts?.language = Locale.forLanguageTag("en-IN")
                tts?.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            }
        }
        val q = "cli=" + URLEncoder.encode(cli, "UTF-8") + "&lang=$lang&agent=1"
        val url = Prefs.server.replaceFirst(Regex("^http"), "ws") + "/ws/caller?$q"
        ws = Api.http.newWebSocket(Api.request("").url(url).build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                emitLocal("connected")
                if (clip == null) startMic() else startClip(clip)
                startPlayer()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val m = try {
                    JSONObject(text)
                } catch (e: Exception) {
                    return
                }
                when (m.optString("type")) {
                    "ping" -> webSocket.send(JSONObject().put("type", "pong").put("t", m.opt("t")).toString())
                    "agent" -> if (!m.optBoolean("audio")) speakLocally(m.optString("say"), m.has("challenge"))
                    "ended", "busy", "error" -> stop(sendHangup = false)
                }
                events.tryEmit(m)
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                playQueue.offer(Mulaw.decode(bytes.toByteArray())) // the agent's voice, spoken by the bank
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.w("BankCall", "call dropped: $t")
                emitLocal("dropped")
                stop(sendHangup = false)
            }
        })
    }

    fun stop(sendHangup: Boolean = true) {
        if (!active) return
        active = false
        if (sendHangup) ws?.send("""{"type":"hangup"}""")
        ws?.close(1000, "hangup")
        ws = null
        record?.let { runCatching { it.stop() }; it.release() }
        record = null
        track?.let { runCatching { it.stop() }; it.release() }
        track = null
        tts?.shutdown()
        tts = null
        val am = appContext.getSystemService(AudioManager::class.java)
        am.clearCommunicationDevice()
        am.mode = AudioManager.MODE_NORMAL
        emitLocal("ended")
    }

    /** Attack mode: the words the cloned voice "says" (a fraudster types them into the clone's TTS). */
    fun sendTyped(text: String) {
        ws?.send(JSONObject().put("type", "typed").put("text", text).toString())
    }

    fun mute(on: Boolean) {
        userMuted = on
    }

    /** Loudspeaker (default, so judges can hear the agent at a table) or the earpiece. */
    fun speaker(on: Boolean) {
        val am = appContext.getSystemService(AudioManager::class.java)
        val want = if (on) AudioDeviceInfo.TYPE_BUILTIN_SPEAKER else AudioDeviceInfo.TYPE_BUILTIN_EARPIECE
        am.availableCommunicationDevices.firstOrNull { it.type == want }?.let { am.setCommunicationDevice(it) }
    }

    private fun emitLocal(state: String) = events.tryEmit(JSONObject().put("type", "local_state").put("state", state))

    private fun send(frame: ShortArray) {
        ws?.send(Mulaw.encode(frame).toByteString())
    }

    @SuppressLint("MissingPermission") // the call screen asks for the mic before starting
    private fun startMic() {
        val min = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val r = AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(min, FRAME * 2 * 10))
        record = r
        if (AcousticEchoCanceler.isAvailable()) AcousticEchoCanceler.create(r.audioSessionId)?.enabled = true
        if (NoiseSuppressor.isAvailable()) NoiseSuppressor.create(r.audioSessionId)?.enabled = true
        r.startRecording()
        thread(name = "bank-call-mic") {
            val buf = ShortArray(FRAME)
            val silence = ShortArray(FRAME)
            while (active && record === r) {
                var got = 0
                while (got < FRAME && active) {
                    val n = r.read(buf, got, FRAME - got)
                    if (n <= 0) break
                    got += n
                }
                val agentTalking = SystemClock.elapsedRealtime() < agentPlayingUntil
                if (got == FRAME) send(if (micMuted || userMuted || agentTalking) silence else buf)
            }
        }
    }

    /** Attack mode: the clip is sent instead of the mic, paced like real time. */
    private fun startClip(clip: ShortArray) {
        thread(name = "bank-call-clip") {
            val silence = ShortArray(FRAME)
            var next = SystemClock.elapsedRealtime()
            // like a real call: let the agent greet first (about 4 s), then the cloned voice speaks
            repeat(200) {
                if (!active) return@thread
                send(silence)
                next += 20
                SystemClock.sleep(maxOf(0, next - SystemClock.elapsedRealtime()))
            }
            var i = 0
            while (active) {
                val f = if (i < clip.size) clip.copyOfRange(i, min(i + FRAME, clip.size)).copyOf(FRAME) else silence
                i += FRAME
                send(f)
                next += 20
                SystemClock.sleep(maxOf(0, next - SystemClock.elapsedRealtime()))
            }
        }
    }

    private fun startPlayer() {
        val attrs = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
        val fmt = AudioFormat.Builder().setSampleRate(RATE).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build()
        val t = AudioTrack.Builder().setAudioAttributes(attrs).setAudioFormat(fmt).setBufferSizeInBytes(RATE / 2).setTransferMode(AudioTrack.MODE_STREAM).build()
        track = t
        t.play()
        thread(name = "bank-call-speaker") {
            // ~120 ms of jitter buffer before the first frame, as the browser softphone does
            while (active && playQueue.size < 6) SystemClock.sleep(10)
            while (active && track === t) {
                val f = playQueue.poll(200, java.util.concurrent.TimeUnit.MILLISECONDS) ?: continue
                // write() returns once the frame is queued, ~a buffer ahead of the speaker: cover that tail too
                agentPlayingUntil = SystemClock.elapsedRealtime() + 500
                t.write(f, 0, f.size)
            }
        }
    }

    /** When the bank sends an agent line as text only (its voice service is down), the phone reads it. */
    private fun speakLocally(text: String, challenge: Boolean) {
        val engine = tts ?: return
        val id = "line" + SystemClock.elapsedRealtime()
        engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {
                micMuted = true
            }

            override fun onDone(utteranceId: String?) {
                Thread.sleep(250) // let the speaker's echo die away
                micMuted = false
                if (challenge) ws?.send("""{"type":"read_done"}""")
            }

            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) {
                micMuted = false
            }
        })
        engine.speak(text, TextToSpeech.QUEUE_ADD, null, id)
    }
}

/** G.711 mu-law, as phone networks carry voice. */
object Mulaw {
    private const val BIAS = 0x84
    private const val CLIP = 32635

    fun encode(pcm: ShortArray): ByteArray = ByteArray(pcm.size) { i ->
        var s = pcm[i].toInt()
        val sign = if (s < 0) 0x80 else 0
        if (s < 0) s = -s
        if (s > CLIP) s = CLIP
        s += BIAS
        var exp = 7
        var mask = 0x4000
        while (exp > 0 && s and mask == 0) {
            exp--
            mask = mask shr 1
        }
        val mant = (s shr (exp + 3)) and 0x0F
        (sign or (exp shl 4) or mant).inv().toByte()
    }

    fun decode(mu: ByteArray): ShortArray = ShortArray(mu.size) { i ->
        val u = mu[i].toInt().inv() and 0xFF
        val sign = u and 0x80
        val exp = (u shr 4) and 0x07
        val mant = u and 0x0F
        var s = ((mant shl 3) + BIAS) shl exp
        s -= BIAS
        (if (sign != 0) -s else s).toShort()
    }
}

/** Reads a PCM WAV (any rate, mono or stereo, 16-bit) into 8 kHz mono samples for attack mode. */
object Wav {
    fun to8k(bytes: ByteArray): ShortArray {
        val b = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        require(String(bytes, 0, 4) == "RIFF" && String(bytes, 8, 4) == "WAVE") { "not a WAV file" }
        var pos = 12
        var rate = 16000
        var channels = 1
        var bits = 16
        var data: ShortArray? = null
        while (pos + 8 <= bytes.size) {
            val id = String(bytes, pos, 4)
            val len = b.getInt(pos + 4)
            if (id == "fmt ") {
                channels = b.getShort(pos + 10).toInt()
                rate = b.getInt(pos + 12)
                bits = b.getShort(pos + 22).toInt()
            } else if (id == "data") {
                require(bits == 16) { "16-bit WAV only" }
                val n = min(len, bytes.size - pos - 8) / 2 / channels
                data = ShortArray(n) { i -> b.getShort(pos + 8 + i * 2 * channels) }
                break
            }
            pos += 8 + len + (len and 1)
        }
        val x = data ?: error("WAV has no audio")
        if (rate == 8000) return x
        val out = ShortArray((x.size.toLong() * 8000 / rate).toInt())
        // average the source samples that fall in each output sample: a crude low-pass, fine for a demo clip
        val step = rate / 8000.0
        for (i in out.indices) {
            val a = (i * step).toInt()
            val e = min(x.size, ((i + 1) * step).toInt().coerceAtLeast(a + 1))
            var sum = 0L
            for (j in a until e) sum += x[j]
            out[i] = (sum / (e - a)).toInt().toShort()
        }
        val peak = out.maxOf { abs(it.toInt()) }.coerceAtLeast(1)
        return if (peak < 8000) ShortArray(out.size) { (out[it] * 8000 / peak).toShort() } else out
    }
}
