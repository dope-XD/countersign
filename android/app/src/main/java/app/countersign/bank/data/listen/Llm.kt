package app.countersign.bank.data.listen

import app.countersign.bank.data.Reason
import app.countersign.bank.data.ScamType
import org.json.JSONObject

/*
 * The smarter check's words in and out: the prompt (assets/llm_prompt.txt, the last ~1,500 characters and the signal
 * ids) and the parser for the model's JSON answer. Pure Kotlin; LlmCheck.kt runs the model. Port of
 * engine/listener/llm.py; keep the two identical (HybridTest checks shared vectors).
 */

const val LLM_MAX_CHARS = 1500
const val LLM_MAX_REASON = 160
val LLM_VERDICTS = setOf("scam", "unsure", "ok")

/** What the smarter check said: `scam`, `unsure` or `ok`, a scam type, one plain reason in both languages. */
data class LlmVerdict(val verdict: String, val type: String = "unknown", val reasonEn: String = "", val reasonHi: String = "") {
    val reason: Reason? get() = if (reasonEn.isBlank() && reasonHi.isBlank()) null else Reason(reasonEn, reasonHi)
}

/** The end of the call so far: the last [maxChars] characters, cut at a word boundary. */
fun llmTail(transcript: String, maxChars: Int = LLM_MAX_CHARS): String {
    val t = transcript.split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ")
    if (t.length <= maxChars) return t
    val cut = t.substring(t.length - maxChars)
    val i = cut.indexOf(' ')
    return if (i in 0 until 40) cut.substring(i + 1) else cut
}

fun llmPrompt(template: String, transcript: String, signals: Set<String>): String {
    val sig = signals.sorted().joinToString(", ").ifEmpty { "nothing" }
    return template.replace("{signals}", sig).replace("{transcript}", llmTail(transcript))
}

private fun clean(s: Any?): String = if (s is String) s.split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ").take(LLM_MAX_REASON) else ""

/** The first JSON object in the model's output (it may wrap it in ``` fences or add words around it); null if unusable. */
fun parseLlm(output: String): LlmVerdict? {
    val m = Regex("\\{.*?\\}", RegexOption.DOT_MATCHES_ALL).find(output) ?: return null
    val d = runCatching { JSONObject(m.value) }.getOrNull() ?: return null
    val v = d.opt("verdict")?.toString()?.trim()?.lowercase() ?: return null
    if (v !in LLM_VERDICTS) return null
    val t = d.opt("type")?.toString()?.trim()?.lowercase() ?: "unknown"
    return LlmVerdict(v, if (ScamType.entries.any { it.wire == t }) t else "unknown", clean(d.opt("reason_en")), clean(d.opt("reason_hi")))
}
