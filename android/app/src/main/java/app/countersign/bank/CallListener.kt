package app.countersign.bank

import android.content.Context
import android.util.Log
import app.countersign.bank.data.RealRepository
import app.countersign.bank.data.Repo
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/**
 * The call listener's brain, all on the phone: the mic frames from [ListenService] → [Speech.Live] (VAD + speech-to-text)
 * → [CallRisk] (cues + our classifier + context, via the Analyzer). The first ~20 s of speech also go once to
 * [VoiceCheck]. Nothing is recorded or sent: only the level, the scam type and cue ids leave the phone, in a scam alert.
 */
object CallListener {
    private const val TAG = "CallListener"
    private const val VOICE_SAMPLES = 20 * 16_000
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var jobs = mutableListOf<Job>()
    private var live: Speech.Live? = null
    private var callId: String? = null
    private var voice = FloatArray(VOICE_SAMPLES)
    private var voiceN = 0
    private var voiceDone = false

    fun start(c: Context) {
        if (jobs.isNotEmpty()) return
        val app = c.applicationContext
        val repo = Repo.instance
        (repo as? RealRepository)?.analysisReady = Speech.ready(app)
        jobs += scope.launch {
            repo.call.map { it?.id }.distinctUntilChanged().collect { id -> switchTo(app, id) }
        }
        jobs += scope.launch {
            ListenService.audio.collect { frame ->
                val l = live ?: return@collect
                l.accept(frame)
                if (!voiceDone) collectVoice(app, frame)
            }
        }
    }

    fun stop() {
        jobs.forEach { it.cancel() }
        jobs.clear()
        switchTo(null, null)
    }

    @Synchronized
    private fun switchTo(c: Context?, id: String?) {
        if (id == callId) return
        live?.close()
        live = null
        callId = id
        voiceN = 0
        voiceDone = false
        if (c == null || id == null) return
        if (!Speech.ready(c)) {
            Log.i(TAG, "no model pack: listening for context only")
            return
        }
        live = Speech.Live(c) { texts -> texts.forEach { t -> CallRisk.update { heard(t) } } }
        Log.i(TAG, "listening to call")
    }

    /** Loud-enough frames only (rough speech gate), until 20 s are collected; then one voice score for the call. */
    private fun collectVoice(c: Context, frame: ShortArray) {
        var e = 0.0
        for (s in frame) e += s.toDouble() * s
        if (e / frame.size < 300.0 * 300.0) return
        for (s in frame) {
            if (voiceN >= VOICE_SAMPLES) break
            voice[voiceN++] = s / 32768f
        }
        if (voiceN >= VOICE_SAMPLES) {
            voiceDone = true
            val x = voice.copyOf()
            scope.launch {
                val p = runCatching { VoiceCheck.score(c, x) }.getOrNull()
                Log.i(TAG, "voice check: ${p?.let { "%.2f".format(it) } ?: "no model"}")
                if (p != null) CallRisk.update { voice(p) }
            }
        }
    }
}
