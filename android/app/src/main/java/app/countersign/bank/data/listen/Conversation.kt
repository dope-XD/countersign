package app.countersign.bank.data.listen

import org.json.JSONObject
import java.text.Normalizer
import kotlin.math.max
import kotlin.math.sqrt

/*
 * The conversation check: what the phone decides a call with when the model pack is installed.
 *   recognised segment → the call so far (last ~1,200 characters, one script) → conversation model → p
 *                      → scam-move matcher (base e5) → the move it makes, for "why"
 *   p over segments + context + voice → [Accumulator] → none / watch / warn / scam, with plain-words reasons
 * The model decides; the matcher only names what was said, when that segment made the risk rise.
 * Pure Kotlin, no Android (ConversationTest runs it on the JVM with shared vectors).
 * Port of engine/listener/conversation.py; keep the two identical.
 */

const val CONV_PREFIX = "query: "
const val CONV_MAX_CHARS = 1200
const val CONV_SEP = " | "
const val CONV_MAX_LEN = 320

/** One segment as the model reads it: normalised, kept in its own script (e5 reads Devanagari natively), one space between words. */
fun segmentText(t: String): String = normalize(t).joinToString(" ")

/** The last [CONV_MAX_CHARS] characters of the call so far, cut at a segment boundary where possible. */
fun convWindow(segments: List<String>): String {
    val s = segments.map(::segmentText).filter { it.isNotEmpty() }.joinToString(CONV_SEP)
    if (s.length <= CONV_MAX_CHARS) return s
    val cut = s.substring(s.length - CONV_MAX_CHARS)
    val i = cut.indexOf(CONV_SEP)
    return if (i in 0 until 200) cut.substring(i + CONV_SEP.length) else cut
}

/** multilingual-e5-small's tokenizer: NFKC, Metaspace, unigram Viterbi; <s> … </s>; keeps the newest tokens. */
class E5Tokenizer(private val piece: Map<String, Pair<Int, Float>>) {
    private val longest = piece.keys.maxOf { it.length }
    private val unkScore = piece.values.minOf { it.second } - 10f

    fun word(w: String): List<Int> {
        val n = w.length
        val best = DoubleArray(n + 1) { NEG }
        val from = IntArray(n + 1)
        val tok = IntArray(n + 1)
        best[0] = 0.0
        for (i in 0 until n) {
            if (best[i] <= NEG) continue
            // a surrogate pair is one character to SentencePiece: never split it
            val step = if (Character.isHighSurrogate(w[i]) && i + 1 < n) 2 else 1
            var hit = false
            for (j in i + 1..minOf(n, i + longest)) {
                val e = piece[w.substring(i, j)] ?: continue
                if (j == i + step) hit = true
                val s = best[i] + e.second
                if (s > best[j]) {
                    best[j] = s; from[j] = i; tok[j] = e.first
                }
            }
            if (!hit) {
                val s = best[i] + unkScore
                if (s > best[i + step]) {
                    best[i + step] = s; from[i + step] = i; tok[i + step] = UNK
                }
            }
        }
        val out = ArrayList<Int>()
        var j = n
        while (j > 0) {
            out.add(tok[j]); j = from[j]
        }
        out.reverse()
        return out
    }

    fun encode(text: String, maxLen: Int = CONV_MAX_LEN): LongArray {
        val ids = ArrayList<Int>()
        // as e5's normalizer and Metaspace: NFKC, runs of spaces → one, every space → ▁, a ▁ in front, cut before each ▁
        val s = "▁" + Normalizer.normalize(text, Normalizer.Form.NFKC).replace(Regex(" {2,}"), " ").replace(' ', '▁')
        var start = 0
        while (start < s.length) {
            var end = s.indexOf('▁', start + 1)
            if (end < 0) end = s.length
            ids.addAll(word(s.substring(start, end)))
            start = end
        }
        val keep = ids.takeLast(maxLen - 2) // left truncation: the newest words are never cut
        return LongArray(keep.size + 2).also { a ->
            a[0] = BOS.toLong(); keep.forEachIndexed { k, v -> a[k + 1] = v.toLong() }; a[a.size - 1] = EOS.toLong()
        }
    }

    companion object {
        const val BOS = 0
        const val EOS = 2
        const val UNK = 3
        private const val NEG = -1e18

        /** assets/e5_vocab.txt: "id \t piece \t score" per line (engine/listener/conversation.py write_vocab). */
        fun parse(text: String): E5Tokenizer {
            val m = HashMap<String, Pair<Int, Float>>(300_000)
            var start = 0
            while (start < text.length) {
                var end = text.indexOf('\n', start)
                if (end < 0) end = text.length
                val a = text.indexOf('\t', start)
                val b = text.indexOf('\t', a + 1)
                if (a in start until end && b in a + 1 until end) m[text.substring(a + 1, b)] = text.substring(start, a).toInt() to text.substring(b + 1, end).toFloat()
                start = end + 1
            }
            return E5Tokenizer(m)
        }
    }
}

data class Move(val id: String, val group: String, val category: String?, val similarity: Float)

/** The scam-move matcher (ml/moves.py): a segment's embedding → the move it makes, if it clears that move's threshold. */
class Matcher(json: String) {
    private val centre: FloatArray
    private val ids: List<String>
    private val groups: List<String>
    private val cats: List<String?>
    private val thr: FloatArray
    private val vecs: Array<FloatArray>
    private val owner: IntArray

    init {
        val d = JSONObject(json)
        centre = d.getJSONArray("centre").let { a -> FloatArray(a.length()) { a.getDouble(it).toFloat() } }
        val ms = d.getJSONArray("moves")
        ids = (0 until ms.length()).map { ms.getJSONObject(it).getString("id") }
        groups = (0 until ms.length()).map { ms.getJSONObject(it).getString("group") }
        cats = (0 until ms.length()).map { ms.getJSONObject(it).let { o -> if (o.isNull("category")) null else o.getString("category") } }
        thr = FloatArray(ms.length()) { ms.getJSONObject(it).getDouble("threshold").toFloat() }
        val ds = d.getJSONArray("descriptions")
        vecs = Array(ds.length()) { k -> ds.getJSONObject(k).getJSONArray("vec").let { a -> FloatArray(a.length()) { a.getDouble(it).toFloat() } } }
        owner = IntArray(ds.length()) { ids.indexOf(ds.getJSONObject(it).getString("move")) }
    }

    /** The move this segment makes if it clears that move's threshold; with [guess], the closest unsafe move anyway. */
    fun match(embedding: FloatArray, guess: Boolean = false): Move? {
        val v = FloatArray(embedding.size) { embedding[it] - centre[it] }
        val norm = max(sqrt(v.fold(0.0) { a, x -> a + x * x }).toFloat(), 1e-9f)
        for (i in v.indices) v[i] /= norm
        val best = FloatArray(ids.size) { -2f }
        for (k in vecs.indices) {
            var s = 0f
            for (i in v.indices) s += vecs[k][i] * v[i]
            if (s > best[owner[k]]) best[owner[k]] = s
        }
        val k = best.indices.maxBy { best[it] }
        if (best[k] >= thr[k]) return Move(ids[k], groups[k], cats[k], best[k])
        if (!guess) return null
        val u = best.indices.filter { cats[it] != null }.maxBy { best[it] }
        return Move(ids[u], groups[u], cats[u], best[u])
    }
}

class ConvConfig(json: String) {
    private val c = JSONObject(json)
    private fun set(k: String) = c.getJSONArray(k).let { a -> (0 until a.length()).map { a.getString(it) }.toSet() }

    val smooth = c.getInt("smooth")
    val scamRun = c.getInt("scam_run")
    val whyRise = c.getDouble("why_rise")
    val trustedContext = set("trusted_context")
    val warnContext = set("warn_context")
    val scamContext = set("scam_context")
    val shownContext = set("shown_context")
    val main = Thresholds(c)
    val trusted = Thresholds(c.getJSONObject("trusted"))

    class Thresholds(o: JSONObject) {
        val watch = o.getDouble("t_watch")
        val warn = o.getDouble("t_warn")
        val scam = o.getDouble("t_scam")
    }
}

/**
 * p for each segment → the call's level; levels never go down. watch / warn: the mean p of the last `smooth`
 * segments reaches t_watch / t_warn; scam: p ≥ t_scam on `scam_run` segments in a row. A known contact or a verified
 * caller uses the stricter `trusted` thresholds. A failed caller check or a remote-control app reaches warn alone, and
 * makes scam with the conversation at warn. The voice-clone check lifts watch to warn, never makes scam.
 */
class Accumulator(private val cfg: ConvConfig) {
    private val ps = ArrayList<Double>()
    var modelLevel = "none"
        private set
    var level = "none"
        private set

    fun feed(p: Double, context: Set<String>): String {
        ps.add(p)
        val th = if (context.any { it in cfg.trustedContext }) cfg.trusted else cfg.main
        val recent = ps.takeLast(cfg.smooth)
        val s = recent.sum() / recent.size
        val run = ps.takeLast(cfg.scamRun)
        var lvl = "none"
        if (s >= th.watch) lvl = "watch"
        if (s >= th.warn) lvl = "warn"
        if (run.size == cfg.scamRun && run.min() >= th.scam) lvl = "scam"
        modelLevel = higher(modelLevel, lvl)
        return judge(context)
    }

    fun judge(context: Set<String>): String {
        var lvl = modelLevel
        if (context.any { it in cfg.warnContext }) lvl = higher(lvl, "warn")
        if ("synthetic_voice" in context && lvl == "watch") lvl = "warn"
        if (context.any { it in cfg.scamContext } && LEVELS.indexOf(modelLevel) >= LEVELS.indexOf("warn")) lvl = "scam"
        level = higher(level, lvl)
        return level
    }
}

/** The two on-phone e5 models (int8 ONNX in the model pack); ConversationModels on Android, fakes in tests. */
interface ConvModels {
    /** P(the caller has made a scam move yet) for the call so far (a [convWindow]). */
    fun p(window: String): Double

    /** The base e5 embedding of one segment's [segmentText] (mean-pooled, L2-normalised). */
    fun embed(segment: String): FloatArray
}

/** What conversation mode needs: the two models, the move matcher (moves.json) and the thresholds (conv.json). */
class ConvKit(val models: ConvModels, val matcher: Matcher, val cfg: ConvConfig)

/**
 * A whole recording's transcript or a message → segments, as speech-to-text would give them on a call: split at
 * sentence ends, then at most [maxWords] words each.
 */
fun textSegments(text: String, maxWords: Int = 20): List<String> =
    text.split(Regex("[.!?।\n|]+")).flatMap { s ->
        val w = s.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
        w.chunked(maxWords).map { it.joinToString(" ") }
    }.filter { it.isNotBlank() }

/** One call: feed recognised segments one by one; read [verdict]. */
class ConvCall(private val models: ConvModels, private val matcher: Matcher, private val cfg: ConvConfig, private val rules: Rules) {
    private val segments = ArrayList<String>()
    private val acc = Accumulator(cfg)
    private val reasons = ArrayList<String>()
    private var context = emptySet<String>()
    var lastP: Double? = null
        private set

    fun feed(segment: String): Verdict {
        if (segmentText(segment).isEmpty()) return verdict()
        segments.add(segment)
        val p = models.p(convWindow(segments))
        val rise = p - (lastP ?: 0.0)
        lastP = p
        val before = acc.modelLevel
        acc.feed(p, context)
        // name the move only when this segment made the risk rise (or the level went up); once the model has
        // reached amber with no reason named yet, its closest move is named even below the matcher's threshold
        val warned = LEVELS.indexOf(acc.modelLevel) >= LEVELS.indexOf("warn")
        if (rise >= cfg.whyRise || acc.modelLevel != before || (warned && reasons.isEmpty())) {
            val m = matcher.match(models.embed(segmentText(segment)), guess = warned && reasons.isEmpty())
            if (m?.category != null && m.category !in reasons) reasons.add(m.category)
        }
        return verdict()
    }

    fun context(signals: Set<String>): Verdict {
        context = signals
        acc.judge(context)
        return verdict()
    }

    fun verdict(): Verdict {
        val lvl = acc.judge(context)
        val why = reasons + context.filter { it in cfg.shownContext }.sorted()
        var kind = if (lvl != "none") scamType(reasons.toSet(), rules) else "unknown"
        if (kind == "unknown" && "caller_check_failed" in context && lvl != "none") kind = "impersonation"
        val sources = buildSet {
            if (acc.modelLevel != "none") add("phone_ai")
            if (context.any { it in cfg.warnContext || it in cfg.scamContext }) add("context")
            if ("synthetic_voice" in context) add("voice")
        }
        return Verdict(lvl, kind, why, sources.sorted())
    }
}
