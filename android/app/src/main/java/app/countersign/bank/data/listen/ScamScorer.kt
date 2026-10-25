package app.countersign.bank.data.listen

import org.json.JSONObject
import java.text.Normalizer

/*
 * Cue scoring for the call listener: which scam cue categories the call's words have shown so far.
 * Rules: assets/scam_patterns.json. Port of engine/listener/rules.py; keep the two identical
 * (ScamScorerTest checks every shared transcript against the Python result).
 * Owned by agent A (the contract); agent C feeds it speech-to-text.
 */

class Rules(
    /** category -> phrases as word lists, in file order */
    val categories: LinkedHashMap<String, List<List<String>>>,
    val weak: Set<String>,
    val action: Set<String>,
    val negatable: Set<String>,
    val negations: Set<String>,
    val negBefore: Int,
    val negAfter: Int,
    /** word pairs that aren't negations ("nahi to" = otherwise) */
    val negExceptions: Set<List<String>>,
    val types: List<TypeRule>,
    val maxPhrase: Int,
) {
    class TypeRule(val type: String, val all: Set<String>, val any: Set<String>, val plus: Set<String>, val bonus: Int)

    companion object {
        fun parse(json: String): Rules {
            val d = JSONObject(json)
            val cats = LinkedHashMap<String, List<List<String>>>()
            val weak = mutableSetOf<String>()
            val action = mutableSetOf<String>()
            val neg = mutableSetOf<String>()
            val c = d.getJSONObject("categories")
            for (name in c.keys()) {
                val o = c.getJSONObject(name)
                val ps = o.getJSONArray("phrases")
                cats[name] = (0 until ps.length()).map { normalize(ps.getString(it)) }.filter { it.isNotEmpty() }
                if (o.optBoolean("weak")) weak += name
                if (o.optBoolean("action")) action += name
                if (o.optBoolean("negatable")) neg += name
            }
            val w = d.getJSONObject("negation_window")
            val negs = d.getJSONArray("negations")
            val exc = d.getJSONArray("negation_exceptions")
            val ts = d.getJSONArray("types")
            fun set(o: JSONObject, k: String) = o.getJSONArray(k).let { a -> (0 until a.length()).map { a.getString(it) }.toSet() }
            return Rules(
                categories = cats,
                weak = weak,
                action = action,
                negatable = neg,
                negations = (0 until negs.length()).flatMap { normalize(negs.getString(it)) }.toSet(),
                negBefore = w.getInt("before"),
                negAfter = w.getInt("after"),
                negExceptions = (0 until exc.length()).map { normalize(exc.getString(it)) }.toSet(),
                types = (0 until ts.length()).map { i ->
                    val t = ts.getJSONObject(i)
                    TypeRule(t.getString("type"), set(t, "all"), set(t, "any"), set(t, "plus"), t.optInt("bonus", 0))
                },
                maxPhrase = cats.values.flatten().maxOf { it.size },
            )
        }
    }
}

/** Lower case; apostrophes dropped; anything but letters, marks, digits and "_" becomes a space. */
fun normalize(text: String): List<String> {
    val t = Normalizer.normalize(text, Normalizer.Form.NFC).lowercase().replace("'", "").replace("’", "")
    val sb = StringBuilder()
    var i = 0
    while (i < t.length) {
        val cp = t.codePointAt(i)
        val keep = cp == '_'.code || when (Character.getType(cp)) {
            Character.UPPERCASE_LETTER.toInt(), Character.LOWERCASE_LETTER.toInt(), Character.TITLECASE_LETTER.toInt(),
            Character.MODIFIER_LETTER.toInt(), Character.OTHER_LETTER.toInt(),
            Character.NON_SPACING_MARK.toInt(), Character.ENCLOSING_MARK.toInt(), Character.COMBINING_SPACING_MARK.toInt(),
            Character.DECIMAL_DIGIT_NUMBER.toInt(), Character.LETTER_NUMBER.toInt(), Character.OTHER_NUMBER.toInt(),
            -> true
            else -> false
        }
        if (keep) sb.appendCodePoint(cp) else sb.append(' ')
        i += Character.charCount(cp)
    }
    return sb.split(' ').filter { it.isNotEmpty() }
}

private fun allowedEdits(word: String): Int {
    val n = word.codePointCount(0, word.length)
    return if (n >= 9) 2 else if (n >= 5) 1 else 0
}

/** Levenshtein distance over code points, giving up (limit + 1) once it must exceed limit. */
private fun lev(a: String, b: String, limit: Int): Int {
    val x = a.codePoints().toArray()
    val y = b.codePoints().toArray()
    if (kotlin.math.abs(x.size - y.size) > limit) return limit + 1
    var prev = IntArray(y.size + 1) { it }
    for (i in 1..x.size) {
        val cur = IntArray(y.size + 1)
        cur[0] = i
        var best = cur[0]
        for (j in 1..y.size) {
            cur[j] = minOf(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + if (x[i - 1] != y[j - 1]) 1 else 0)
            best = minOf(best, cur[j])
        }
        if (best > limit) return limit + 1
        prev = cur
    }
    return prev[y.size]
}

fun wordMatches(phraseWord: String, token: String): Boolean {
    if (phraseWord == token) return true
    val k = allowedEdits(phraseWord)
    return k > 0 && lev(phraseWord, token, k) <= k
}

/** Spans (first, last token index) where [phrase] starts in tokens[start, stop); one extra word allowed between phrase words. */
internal fun find(phrase: List<String>, tokens: List<String>, start: Int, stop: Int): List<IntArray> {
    val spans = mutableListOf<IntArray>()
    for (i in start until minOf(stop, tokens.size)) {
        if (!wordMatches(phrase[0], tokens[i])) continue
        var pos = i
        var ok = true
        for (w in phrase.drop(1)) {
            if (pos + 1 < tokens.size && wordMatches(w, tokens[pos + 1])) {
                pos += 1
            } else if (pos + 2 < tokens.size && wordMatches(w, tokens[pos + 2])) {
                pos += 2
            } else {
                ok = false
                break
            }
        }
        if (ok) spans += intArrayOf(i, pos)
    }
    return spans
}

internal fun negated(span: IntArray, tokens: List<String>, r: Rules): Boolean {
    val (lo, hi) = span[0] to span[1]
    val around = (maxOf(0, lo - r.negBefore) until lo) + (hi + 1 until minOf(tokens.size, hi + 1 + r.negAfter))
    return around.any { k -> tokens[k] in r.negations && tokens.subList(k, minOf(tokens.size, k + 2)) !in r.negExceptions }
}

fun scamType(cats: Set<String>, r: Rules): String {
    var best = "unknown"
    var bestScore = 0
    for (t in r.types) {
        if (!cats.containsAll(t.all)) continue
        if (t.any.isNotEmpty() && (t.any intersect cats).isEmpty()) continue
        val score = t.all.size + (t.any intersect cats).size + (t.plus intersect cats).size + t.bonus
        if (score > bestScore) {
            best = t.type
            bestScore = score
        }
    }
    return best
}

/** [evidence]: category -> the phrase that matched (debugging only; never sent anywhere). */
data class CueResult(val categories: List<String>, val type: String, val evidence: Map<String, String>) {
    val discussion get() = "discussion" in categories
}

/**
 * Feed it the call's words as they arrive; it keeps what it has found. Words that can still be
 * negated by what comes next stay provisional until enough words follow them.
 */
class CallScorer(private val r: Rules) {
    private var tokens = mutableListOf<String>()
    private val found = LinkedHashMap<String, String>()
    private var scanned = 0

    fun feed(text: String): CueResult {
        tokens.addAll(normalize(text))
        if (tokens.size > MAX_TOKENS) {
            val cut = tokens.size - MAX_TOKENS
            tokens = tokens.subList(cut, tokens.size).toMutableList()
            scanned = maxOf(0, scanned - cut)
        }
        val finalUpto = maxOf(scanned, tokens.size - r.maxPhrase * 2 - r.negAfter)
        for ((k, v) in scan(scanned, finalUpto)) found.putIfAbsent(k, v)
        scanned = finalUpto
        return result()
    }

    private fun scan(start: Int, stop: Int): Map<String, String> {
        val hits = LinkedHashMap<String, String>()
        for ((cat, phrases) in r.categories) {
            if (cat in found || cat in hits) continue
            for (p in phrases) {
                if (find(p, tokens, start, stop).any { s -> !(cat in r.negatable && negated(s, tokens, r)) }) {
                    hits[cat] = p.joinToString(" ")
                    break
                }
            }
        }
        return hits
    }

    /** Committed categories plus provisional ones from the words not yet final. */
    fun result(): CueResult {
        val both = scan(scanned, tokens.size) + found
        val cats = r.categories.keys.filter { it in both }
        return CueResult(cats, scamType(cats.toSet() - "discussion", r), cats.associateWith { both.getValue(it) })
    }

    companion object {
        const val MAX_TOKENS = 6000 // about 40 minutes of speech; older words are dropped
    }
}

/** Number words a person reads an OTP or card number out with: English, Hinglish, Hindi (exact words only, no fuzzy match). */
val DIGIT_WORDS: Set<String> = (
    "zero one two three four five six seven eight nine " +
        "shunya sunya ek do teen tin char chaar paanch panch chhe che chheh saat sat aath ath nau " +
        "शून्य एक दो तीन चार पांच पाँच छह छः छे सात आठ नौ"
    ).split(" ").toSet()

/** An OTP is 4 to 8 digits; a 10-digit phone number is not one. */
val DIGITS_READ_OUT = 4..8

/** Helplines and short codes are said, not read out. */
val HELPLINES = setOf("1930", "100", "112", "1800", "1600", "181", "1098", "14422", "155260")

/** Lengths of the runs of digits read out in a row: "4 5 2 1", "4521", "char paanch do ek" are each 4. */
fun digitRuns(tokens: List<String>): List<Int> {
    val runs = ArrayList<Int>()
    var n = 0
    for (t in tokens) {
        when {
            t.isNotEmpty() && t.all { it in '0'..'9' } && t !in HELPLINES -> n += t.length
            t in DIGIT_WORDS -> n += 1
            else -> {
                if (n > 0) runs.add(n)
                n = 0
            }
        }
    }
    if (n > 0) runs.add(n)
    return runs
}

/** Someone read out 4 to 8 digits in a row (on an unknown call: likely an OTP or a card's digits). */
fun digitsReadOut(tokens: List<String>): Boolean = digitRuns(tokens).any { it in DIGITS_READ_OUT }
