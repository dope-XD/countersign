package app.countersign.bank

import android.content.Context
import android.util.Log
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.OfflineDolphinModelConfig
import com.k2fsa.sherpa.onnx.OfflineModelConfig
import com.k2fsa.sherpa.onnx.OfflineMoonshineModelConfig
import com.k2fsa.sherpa.onnx.OfflineNemoEncDecCtcModelConfig
import com.k2fsa.sherpa.onnx.OfflineOmnilingualAsrCtcModelConfig
import com.k2fsa.sherpa.onnx.OfflineRecognizer
import com.k2fsa.sherpa.onnx.OfflineRecognizerConfig
import com.k2fsa.sherpa.onnx.SileroVadModelConfig
import com.k2fsa.sherpa.onnx.Vad
import com.k2fsa.sherpa.onnx.VadModelConfig
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

/**
 * On-phone speech-to-text (sherpa-onnx, the same runtime as ml/eval/asr_bakeoff.py): Silero VAD cuts speech into
 * segments, and every recogniser in the model pack (a Hindi-capable one and an English one) decodes each segment.
 * All their texts go to the listener, which copes with Hinglish that way. Audio stays in memory and is dropped.
 */
object Speech {
    private const val TAG = "Speech"
    private var recognizers: List<OfflineRecognizer>? = null
    private var vadPath: String? = null

    fun ready(c: Context) = ModelPack.manifest(c) != null

    @Synchronized
    fun reset() {
        recognizers?.forEach { it.release() }
        recognizers = null
    }

    @Synchronized
    private fun load(c: Context): List<OfflineRecognizer>? {
        recognizers?.let { return it }
        val m = ModelPack.manifest(c) ?: return null
        val dir = ModelPack.dir(c)
        fun f(o: JSONObject, k: String) = File(dir, o.getString(k)).absolutePath
        val asr = m.getJSONArray("asr")
        val list = (0 until asr.length()).map { i ->
            val a = asr.getJSONObject(i)
            val model = OfflineModelConfig().apply {
                tokens = f(a, "tokens")
                numThreads = 2
                provider = "cpu"
                when (a.getString("kind")) {
                    "dolphin" -> dolphin = OfflineDolphinModelConfig(f(a, "model"))
                    "omnilingual" -> omnilingual = OfflineOmnilingualAsrCtcModelConfig(f(a, "model"))
                    "nemo_ctc" -> nemo = OfflineNemoEncDecCtcModelConfig(f(a, "model")) // IndicConformer (Hindi), fast-conformer (English)
                    "moonshine_v2" -> moonshine = OfflineMoonshineModelConfig().apply {
                        encoder = f(a, "encoder")
                        mergedDecoder = f(a, "decoder")
                    }
                    else -> error("unknown model kind ${a.getString("kind")}")
                }
            }
            OfflineRecognizer(null, OfflineRecognizerConfig().apply {
                featConfig = FeatureConfig(16_000, 80)
                modelConfig = model
                decodingMethod = "greedy_search"
            })
        }
        vadPath = File(dir, m.getString("vad")).absolutePath
        Log.i(TAG, "loaded ${list.size} recognisers")
        recognizers = list
        return list
    }

    private fun vad(): Vad = Vad(null, VadModelConfig().apply {
        sileroVadModelConfig = SileroVadModelConfig().apply {
            model = vadPath!!
            threshold = 0.5f
            minSilenceDuration = 0.4f
            minSpeechDuration = 0.25f
            maxSpeechDuration = 12f
            windowSize = 512
        }
        sampleRate = 16_000
        numThreads = 1
    })

    /** Every recogniser's text for one segment. */
    @Synchronized
    private fun decode(rs: List<OfflineRecognizer>, samples: FloatArray): List<String> = rs.map { r ->
        val s = r.createStream()
        s.acceptWaveform(samples, 16_000)
        r.decode(s)
        val t = r.getResult(s).text.trim()
        s.release()
        t
    }

    /** A whole recording (Check a recording). Null when the model pack isn't installed. */
    fun transcribe(c: Context, audio: FloatArray): String? {
        val rs = load(c) ?: return null
        val v = vad()
        val texts = mutableListOf<String>()
        try {
            var i = 0
            while (i < audio.size) {
                v.acceptWaveform(audio.copyOfRange(i, minOf(audio.size, i + 512)))
                i += 512
                while (!v.empty()) {
                    texts += decode(rs, v.front().samples)
                    v.pop()
                }
            }
            v.flush()
            while (!v.empty()) {
                texts += decode(rs, v.front().samples)
                v.pop()
            }
        } finally {
            v.release()
        }
        return texts.filter { it.isNotBlank() }.joinToString(" ")
    }

    /** A live call: feed 20 ms frames; each finished segment's texts go to [onText], off the recording thread. */
    class Live(c: Context, private val onText: (List<String>) -> Unit) {
        private val rs = load(c)
        private val v = if (rs != null) vad() else null
        private val worker = Executors.newSingleThreadExecutor()
        private val buf = FloatArray(512)
        private var n = 0

        val ok get() = rs != null

        fun accept(frame: ShortArray) {
            val vad = v ?: return
            for (s in frame) {
                buf[n++] = s / 32768f
                if (n == buf.size) {
                    vad.acceptWaveform(buf.copyOf())
                    n = 0
                    while (!vad.empty()) {
                        val seg = vad.front().samples
                        vad.pop()
                        worker.execute { runCatching { onText(decode(rs!!, seg).filter { it.isNotBlank() }) }.onFailure { Log.w(TAG, "decode: $it") } }
                    }
                }
            }
        }

        fun close() {
            v?.release()
            worker.shutdown()
        }
    }
}
