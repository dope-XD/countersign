package app.countersign.bank.data.listen

import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.sqrt

/*
 * Our scam classifier: hashed character and word n-grams → logistic regression → p_scam for a transcript or message.
 * Weights: assets/scam_clf.bin (float32, little-endian), settings: assets/scam_clf.json, trained by ml/listener_clf.py.
 * Port of engine/listener/classifier.py; keep the two identical (ScamClassifierTest checks the shared vectors).
 */

private val CONS = mapOf(
    'क' to "k", 'ख' to "kh", 'ग' to "g", 'घ' to "gh", 'ङ' to "n", 'च' to "ch", 'छ' to "chh", 'ज' to "j", 'झ' to "jh", 'ञ' to "n",
    'ट' to "t", 'ठ' to "th", 'ड' to "d", 'ढ' to "dh", 'ण' to "n", 'त' to "t", 'थ' to "th", 'द' to "d", 'ध' to "dh", 'न' to "n",
    'प' to "p", 'फ' to "ph", 'ब' to "b", 'भ' to "bh", 'म' to "m", 'य' to "y", 'र' to "r", 'ल' to "l", 'व' to "v", 'श' to "sh",
    'ष' to "sh", 'स' to "s", 'ह' to "h", 'ळ' to "l",
)
private val VOWELS = mapOf(
    'अ' to "a", 'आ' to "a", 'इ' to "i", 'ई' to "i", 'उ' to "u", 'ऊ' to "u", 'ऋ' to "ri", 'ए' to "e", 'ऐ' to "ai", 'ओ' to "o",
    'औ' to "au", 'ऍ' to "e", 'ऑ' to "o",
)
private val MATRAS = mapOf(
    'ा' to "a", 'ि' to "i", 'ी' to "i", 'ु' to "u", 'ू' to "u", 'ृ' to "ri", 'े' to "e", 'ै' to "ai", 'ो' to "o", 'ौ' to "au",
    'ॅ' to "e", 'ॉ' to "o",
)
private val NUKTA_CONS = mapOf('क' to "q", 'ख' to "kh", 'ग' to "g", 'ज' to "z", 'ड' to "d", 'ढ' to "dh", 'फ' to "f")
private const val VIRAMA = '्'
private const val NUKTA = '़'
private const val VISARGA = 'ः'

/** One token, Devanagari letters → rough Latin as Hinglish is typed ("खाता" → "khata"); the word-final inherent 'a' is silent. */
fun fold(token: String): String {
    if (token.none { it in 'ऀ'..'ॿ' }) return token
    val out = StringBuilder()
    var pendingA = false
    var i = 0
    // every Devanagari character is a single UTF-16 unit, so indexing by Char is safe here
    while (i < token.length) {
        val ch = token[i]
        val next = if (i + 1 < token.length) token[i + 1] else '\u0000'
        when {
            ch in CONS -> {
                if (pendingA) out.append('a')
                if (next == NUKTA) {
                    out.append(NUKTA_CONS[ch] ?: CONS.getValue(ch))
                    i++
                } else {
                    out.append(CONS.getValue(ch))
                }
                pendingA = true
            }
            ch in MATRAS -> {
                out.append(MATRAS.getValue(ch))
                pendingA = false
            }
            ch == VIRAMA -> pendingA = false
            ch in VOWELS -> {
                if (pendingA) out.append('a')
                out.append(VOWELS.getValue(ch))
                pendingA = false
            }
            ch == 'ं' || ch == 'ँ' -> {
                if (pendingA) out.append('a')
                out.append('n')
                pendingA = false
            }
            ch == NUKTA || ch == VISARGA -> {}
            ch in '०'..'९' -> {
                if (pendingA) out.append('a')
                out.append(ch - '०')
                pendingA = false
            }
            else -> {
                if (pendingA) out.append('a')
                out.append(ch)
                pendingA = false
            }
        }
        i++
    }
    return out.toString()
}

/** 32-bit FNV-1a over the UTF-8 bytes, as an unsigned value in a Long. */
fun fnv1a(s: String): Long {
    var h = 0x811C9DC5L
    for (b in s.toByteArray(Charsets.UTF_8)) {
        h = ((h xor (b.toLong() and 0xFF)) * 0x01000193L) and 0xFFFFFFFFL
    }
    return h
}

fun clfTokens(text: String): List<String> = normalize(text).map(::fold)

/** Character n-grams of " token " (by code point), the word, then neighbouring word pairs. */
fun featureStrings(toks: List<String>, nmin: Int, nmax: Int): List<String> {
    val out = ArrayList<String>()
    for (t in toks) {
        val cps = " $t ".codePoints().toArray()
        for (n in nmin..nmax) {
            for (i in 0..cps.size - n) out += "c" + String(cps, i, n)
        }
        out += "w$t"
    }
    for (i in 0 until toks.size - 1) out += "b${toks[i]} ${toks[i + 1]}"
    return out
}

/** Sparse, unit-length feature vector: hashed index → value. */
fun vectorize(text: String, dim: Int, nmin: Int, nmax: Int): Map<Int, Double> {
    val counts = HashMap<Int, Int>()
    for (f in featureStrings(clfTokens(text), nmin, nmax)) {
        val k = (fnv1a(f) % dim).toInt()
        counts[k] = (counts[k] ?: 0) + 1
    }
    val vec = counts.mapValues { 1.0 + ln(it.value.toDouble()) }
    val norm = sqrt(vec.values.sumOf { it * it })
    return if (norm > 0) vec.mapValues { it.value / norm } else emptyMap()
}

class ScamClassifier(private val weights: FloatArray, private val meta: JSONObject) {
    val dim = meta.getInt("dim")
    private val bias = meta.getDouble("bias")
    private val nmin = meta.getInt("ngram_min")
    private val nmax = meta.getInt("ngram_max")
    val minWordsCall = meta.getInt("min_words_call")
    val minWordsText = meta.getInt("min_words_text")

    init {
        require(weights.size == dim) { "scam_clf.bin and scam_clf.json don't match" }
    }

    fun logit(text: String): Double = bias + vectorize(text, dim, nmin, nmax).entries.sumOf { (k, x) -> weights[k] * x }

    fun pScam(text: String): Double {
        val z = logit(text)
        return if (z > -500) 1.0 / (1.0 + exp(-z)) else 0.0
    }

    /** Fusion's judge slot; abstains while there are fewer than [minWords] words. */
    fun judge(text: String, minWords: Int = minWordsCall): Judge =
        if (normalize(text).size < minWords) Judge(0.0, abstain = true) else Judge(pScam(text))

    companion object {
        fun load(bin: ByteArray, json: String): ScamClassifier {
            val fb = ByteBuffer.wrap(bin).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
            val w = FloatArray(fb.remaining()).also { fb.get(it) }
            return ScamClassifier(w, JSONObject(json))
        }
    }
}
