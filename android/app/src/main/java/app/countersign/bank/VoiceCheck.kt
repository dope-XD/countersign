package app.countersign.bank

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.util.Log
import java.io.File
import java.nio.FloatBuffer

/**
 * The voice-clone check (ml/voice_clone.py): the first ~20 s of speech → how likely the voice is AI-made, 0..1.
 * Runs on the phone with onnxruntime. It can only ever raise the amber card (context id synthetic_voice), never the
 * red one, because over a speakerphone its error rate is high (docs/RESULTS.md).
 */
object VoiceCheck {
    private const val TAG = "VoiceCheck"
    private const val DEFAULT_THRESHOLD = 0.5f
    private var session: OrtSession? = null

    @Synchronized
    fun reset() {
        session?.close()
        session = null
    }

    fun threshold(c: Context): Float = ModelPack.manifest(c)?.optJSONObject("voice")?.optDouble("threshold", DEFAULT_THRESHOLD.toDouble())?.toFloat() ?: DEFAULT_THRESHOLD

    private fun seconds(c: Context): Int = ModelPack.manifest(c)?.optJSONObject("voice")?.optInt("seconds", 20) ?: 20

    @Synchronized
    private fun load(c: Context): OrtSession? {
        session?.let { return it }
        val v = ModelPack.manifest(c)?.optJSONObject("voice") ?: return null
        val f = File(ModelPack.dir(c), v.getString("model"))
        if (!f.exists()) return null
        return runCatching {
            OrtEnvironment.getEnvironment().createSession(f.absolutePath, OrtSession.SessionOptions().apply { setIntraOpNumThreads(2) })
        }.onFailure { Log.w(TAG, "voice model not loaded: $it") }.getOrNull().also { session = it }
    }

    /** P(AI voice) for 16 kHz mono audio, from its first seconds; null without the model or with under 2 s of audio. */
    @Synchronized
    fun score(c: Context, audio: FloatArray): Float? {
        if (audio.size < 32_000) return null
        val s = load(c) ?: return null
        val x = audio.copyOfRange(0, minOf(audio.size, seconds(c) * 16_000))
        // the model expects zero-mean, unit-variance audio, as in training
        val mean = x.average().toFloat()
        val sd = kotlin.math.sqrt(x.fold(0.0) { a, v -> a + (v - mean) * (v - mean) } / x.size).toFloat().coerceAtLeast(1e-5f)
        for (i in x.indices) x[i] = (x[i] - mean) / sd
        val env = OrtEnvironment.getEnvironment()
        OnnxTensor.createTensor(env, FloatBuffer.wrap(x), longArrayOf(1, x.size.toLong())).use { t ->
            s.run(mapOf(s.inputNames.first() to t)).use { r ->
                @Suppress("UNCHECKED_CAST")
                val out = (r[0].value as Array<FloatArray>)[0]
                return out.last().coerceIn(0f, 1f)
            }
        }
    }
}
