package app.countersign.bank.spike

import android.Manifest
import android.accessibilityservice.AccessibilityService
import android.annotation.SuppressLint
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.PixelFormat
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.widget.TextView
import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors
import kotlin.math.abs
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.sqrt

/**
 * #37 spike, debug builds only: can an accessibility service hear the caller during a call?
 *
 * While a call is on (audio mode IN_CALL = phone, IN_COMMUNICATION = WhatsApp-style), it records
 * [clipMs] from each source in [SOURCES] in turn, as 16 kHz mono WAV, into
 * Android/data/app.countersign.bank/files/listen_spike/, and appends one JSON line per clip to
 * summary.jsonl there: source, call type, speaker, level, and whether Android silenced the capture.
 * Turn the speaker on or off between clips to cover both. `android/tools/listen_spike.sh` pulls
 * the clips and prints the table for the issue.
 *
 * Android lets an accessibility service keep the mic when its own UI is on screen, so during a call
 * it shows a small TYPE_ACCESSIBILITY_OVERLAY strip (as the real listener will). Each line says
 * whether it was showing.
 *
 * adb shell am broadcast -a app.countersign.bank.SPIKE_CLIP --ei seconds 5     shorter clips
 * adb shell am broadcast -a app.countersign.bank.SPIKE_CLIP --ez overlay false  no strip
 */
class ListenSpike : AccessibilityService() {
    private val worker = Executors.newSingleThreadExecutor()
    private lateinit var audio: AudioManager
    private lateinit var dir: File

    @Volatile private var running = true

    @Volatile private var clipMs = 20_000L

    @Volatile private var useOverlay = true
    private val main = Handler(Looper.getMainLooper())
    private var strip: TextView? = null

    private val config = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            if (i.hasExtra("seconds")) clipMs = i.getIntExtra("seconds", 20).coerceIn(2, 60) * 1000L
            if (i.hasExtra("overlay")) useOverlay = i.getBooleanExtra("overlay", true)
            Log.i(TAG, "clips ${clipMs / 1000} s, overlay $useOverlay")
        }
    }

    private fun showStrip(on: Boolean) = main.post {
        val wm = getSystemService(WindowManager::class.java)
        if (on && strip == null) {
            val v = TextView(this).apply {
                text = "CS Bank listen test is recording this call (team test)"
                setTextColor(Color.WHITE)
                setBackgroundColor(Color.argb(200, 0x8B, 0x1A, 0x1A))
                setPadding(24, 12, 24, 12)
            }
            val lp = WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
                PixelFormat.TRANSLUCENT,
            ).apply { gravity = Gravity.BOTTOM }
            runCatching { wm.addView(v, lp) }.onSuccess { strip = v }.onFailure { Log.w(TAG, "strip not shown: $it") }
        } else if (!on) {
            strip?.let { runCatching { wm.removeView(it) } }
            strip = null
        }
    }

    override fun onServiceConnected() {
        audio = getSystemService(AudioManager::class.java)
        dir = File(getExternalFilesDir(null), "listen_spike").apply { mkdirs() }
        registerReceiver(config, IntentFilter("app.countersign.bank.SPIKE_CLIP"), Context.RECEIVER_EXPORTED)
        Log.i(TAG, "ready on ${Build.MANUFACTURER} ${Build.MODEL}, Android ${Build.VERSION.RELEASE}; clips go to $dir")
        worker.execute { loop() }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}

    override fun onInterrupt() {}

    override fun onDestroy() {
        running = false
        runCatching { unregisterReceiver(config) }
        showStrip(false)
        worker.shutdownNow()
        super.onDestroy()
    }

    private fun callType(): String? = when (audio.mode) {
        AudioManager.MODE_IN_CALL -> "phone"
        AudioManager.MODE_IN_COMMUNICATION -> "internet"
        else -> null
    }

    private fun speakerOn(): Boolean =
        if (Build.VERSION.SDK_INT >= 31) {
            audio.communicationDevice?.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER
        } else {
            @Suppress("DEPRECATION")
            audio.isSpeakerphoneOn
        }

    /** Waits for a call, then records each source in turn for as long as the call lasts. */
    private fun loop() {
        var next = 0
        while (running) {
            if (callType() == null) {
                next = 0
                showStrip(false)
                Thread.sleep(500)
                continue
            }
            if (useOverlay != (strip != null)) {
                showStrip(useOverlay)
                Thread.sleep(500) // let the window appear before recording, so the line says so
            }
            record(SOURCES[next % SOURCES.size])
            next++
        }
    }

    @SuppressLint("MissingPermission") // checked just below; this is a team-only test tool
    private fun record(source: Pair<String, Int>) {
        val (name, id) = source
        val type = callType() ?: return
        val speaker = speakerOn()
        val out = JSONObject()
            .put("time", SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date()))
            .put("phone", "${Build.MANUFACTURER} ${Build.MODEL}")
            .put("android", Build.VERSION.RELEASE)
            .put("call", type)
            .put("speaker", speaker)
            .put("source", name)
            .put("overlay", strip != null)
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            return finish(out.put("result", "no_mic_permission"), pause = true)
        }
        val minBuf = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = try {
            AudioRecord(id, RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, max(minBuf, RATE * 2))
        } catch (e: Exception) {
            return finish(out.put("result", "open_failed: ${e.message}"))
        }
        if (rec.state != AudioRecord.STATE_INITIALIZED) {
            rec.release()
            return finish(out.put("result", "init_failed"))
        }
        val file = File(dir, "${out.getString("time").replace(Regex("[^0-9]"), "")}_${type}_${if (speaker) "spk" else "ear"}_$name.wav")
        val wav = RandomAccessFile(file, "rw").apply {
            setLength(0)
            write(ByteArray(44)) // header, filled in at the end
        }
        var samples = 0L
        var sumSq = 0.0
        var peak = 0
        var silenced: Boolean? = null
        val buf = ShortArray(RATE / 10)
        val bytes = ByteArray(buf.size * 2)
        try {
            rec.startRecording()
            val end = System.currentTimeMillis() + clipMs
            while (running && System.currentTimeMillis() < end && callType() != null) {
                val n = rec.read(buf, 0, buf.size)
                if (n <= 0) continue
                for (k in 0 until n) {
                    val s = buf[k].toInt()
                    sumSq += s.toDouble() * s
                    peak = max(peak, abs(s))
                    bytes[2 * k] = (s and 0xff).toByte()
                    bytes[2 * k + 1] = (s shr 8 and 0xff).toByte()
                }
                wav.write(bytes, 0, n * 2)
                samples += n
                // ask once, a second in: did Android silence us because of the call?
                if (silenced == null && samples >= RATE) {
                    silenced = audio.activeRecordingConfigurations.firstOrNull { it.clientAudioSessionId == rec.audioSessionId }?.isClientSilenced
                }
            }
        } catch (e: Exception) {
            out.put("error", e.message)
        } finally {
            runCatching { rec.stop() }
            rec.release()
            writeHeader(wav, samples)
            wav.close()
        }
        val rms = if (samples > 0) sqrt(sumSq / samples) else 0.0
        finish(
            out.put("result", if (samples > 0) "recorded" else "no_audio")
                .put("seconds", samples / RATE.toDouble())
                .put("rms_dbfs", if (rms > 0) "%.1f".format(Locale.US, 20 * log10(rms / 32768)) else "-inf")
                .put("peak", peak)
                .put("silenced", silenced ?: JSONObject.NULL)
                .put("file", file.name),
        )
    }

    private fun finish(line: JSONObject, pause: Boolean = false) {
        Log.i(TAG, line.toString())
        File(dir, "summary.jsonl").appendText(line.toString() + "\n")
        if (pause) Thread.sleep(5_000) // don't spin while the call lasts
    }

    private fun writeHeader(f: RandomAccessFile, samples: Long) {
        val data = samples * 2
        fun i32(v: Long) = byteArrayOf(v.toByte(), (v shr 8).toByte(), (v shr 16).toByte(), (v shr 24).toByte())
        fun i16(v: Int) = byteArrayOf(v.toByte(), (v shr 8).toByte())
        f.seek(0)
        f.write("RIFF".toByteArray())
        f.write(i32(36 + data))
        f.write("WAVEfmt ".toByteArray())
        f.write(i32(16))
        f.write(i16(1)) // PCM
        f.write(i16(1)) // mono
        f.write(i32(RATE.toLong()))
        f.write(i32(RATE * 2L))
        f.write(i16(2))
        f.write(i16(16))
        f.write("data".toByteArray())
        f.write(i32(data))
    }

    companion object {
        private const val TAG = "ListenSpike"
        private const val RATE = 16_000
        private val SOURCES = listOf(
            "MIC" to MediaRecorder.AudioSource.MIC,
            "VOICE_RECOGNITION" to MediaRecorder.AudioSource.VOICE_RECOGNITION,
            "UNPROCESSED" to MediaRecorder.AudioSource.UNPROCESSED,
            "CAMCORDER" to MediaRecorder.AudioSource.CAMCORDER,
        )
    }
}
