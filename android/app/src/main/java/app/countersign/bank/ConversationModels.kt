package app.countersign.bank

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.util.Log
import app.countersign.bank.data.listen.CONV_MAX_LEN
import app.countersign.bank.data.listen.CONV_PREFIX
import app.countersign.bank.data.listen.ConvModels
import app.countersign.bank.data.listen.E5Tokenizer
import java.io.File
import java.nio.LongBuffer

/**
 * The conversation model (fp32) and the base e5 for the move matcher (int8) (ml/conv_model.py, ml/moves.py), ONNX from the
 * model pack (`conv` in pack.json), run with onnxruntime. Null when the pack has no conversation models: the phone
 * then uses basic mode (cue rules + the small classifier).
 */
class ConversationModels private constructor(private val conv: OrtSession, private val base: OrtSession, private val tok: E5Tokenizer) : ConvModels {
    private val env = OrtEnvironment.getEnvironment()

    private fun run(s: OrtSession, text: String, maxLen: Int): FloatArray {
        val ids = tok.encode(CONV_PREFIX + text, maxLen)
        val shape = longArrayOf(1, ids.size.toLong())
        OnnxTensor.createTensor(env, LongBuffer.wrap(ids), shape).use { a ->
            OnnxTensor.createTensor(env, LongBuffer.wrap(LongArray(ids.size) { 1L }), shape).use { m ->
                s.run(mapOf("input_ids" to a, "attention_mask" to m)).use { r ->
                    return when (val v = r[0].value) {
                        is FloatArray -> v
                        is Array<*> -> v[0] as FloatArray
                        else -> error("unexpected output $v")
                    }
                }
            }
        }
    }

    @Synchronized
    override fun p(window: String): Double = run(conv, window, CONV_MAX_LEN)[0].toDouble().coerceIn(0.0, 1.0)

    @Synchronized
    override fun embed(segment: String): FloatArray = run(base, segment, 64)

    companion object {
        private const val TAG = "ConversationModels"
        private var loaded: ConversationModels? = null
        private var tried = false

        @Synchronized
        fun get(c: Context): ConversationModels? {
            if (tried) return loaded
            val m = ModelPack.manifest(c)?.optJSONObject("conv") ?: return null
            tried = true
            loaded = runCatching {
                val dir = ModelPack.dir(c)
                val opts = OrtSession.SessionOptions().apply { setIntraOpNumThreads(2) }
                val env = OrtEnvironment.getEnvironment()
                val tok = E5Tokenizer.parse(c.assets.open("e5_vocab.txt").bufferedReader().use { it.readText() })
                ConversationModels(
                    env.createSession(File(dir, m.getString("model")).absolutePath, opts),
                    env.createSession(File(dir, m.getString("base")).absolutePath, opts),
                    tok,
                )
            }.onFailure { Log.w(TAG, "conversation models not loaded: $it") }.getOrNull()
            return loaded
        }

        @Synchronized
        fun reset() {
            loaded?.let { it.conv.close(); it.base.close() }
            loaded = null
            tried = false
        }
    }
}
