package app.countersign.bank.data.listen

import app.countersign.bank.data.Risk
import app.countersign.bank.data.RiskLevel
import app.countersign.bank.data.RiskSource
import app.countersign.bank.data.ScamType
import org.json.JSONArray
import org.json.JSONObject

/*
 * Fusion: cues, the LLM judge, context signals and the server's verdict → one level.
 * Rules: assets/fusion.json. Port of engine/listener/fusion.py; keep the two identical.
 * Levels never go down during a call.
 */

val LEVELS = listOf("none", "watch", "warn", "scam")

fun higher(a: String, b: String) = if (LEVELS.indexOf(a) >= LEVELS.indexOf(b)) a else b

/** What an LLM judge said about the transcript so far. */
data class Judge(val pScam: Double, val type: String = "unknown", val abstain: Boolean = false)

data class Verdict(val level: String, val type: String, val cues: List<String>, val sources: List<String>) {
    fun toRisk(since: Long) = Risk(
        level = RiskLevel.entries.first { it.wire == level },
        type = ScamType.entries.firstOrNull { it.wire == type } ?: ScamType.UNKNOWN,
        cues = cues,
        sources = sources.mapNotNull { s -> RiskSource.entries.firstOrNull { it.wire == s } }.toSet(),
        since = since,
    )
}

class FusionConfig(private val f: JSONObject) {
    private fun list(o: JSONObject, k: String): Set<String> = o.getJSONArray(k).strings()
    val watchMin = f.getJSONObject("watch").getInt("min_categories")
    private val w = f.getJSONObject("warn")
    val warnMinStrong = w.getInt("min_strong")
    val warnLlmP = w.getDouble("llm_p")
    val warnLlmMinCats = w.getInt("llm_min_categories")
    val warnContextAlone = list(w, "context_alone")
    private val s = f.getJSONObject("scam")
    val scamCuesMin = s.getInt("cues_min_categories")
    val scamCuesNeedAction = s.getBoolean("cues_need_action")
    val scamCuesNeedType = s.getBoolean("cues_need_type")
    val scamDiscussionBlocks = s.getBoolean("discussion_blocks_cues")
    val scamLlmP = s.getDouble("llm_p")
    val scamLlmMinCats = s.getInt("llm_min_categories")
    val strongContext = list(s, "strong_context")
    val contextAsCategory = list(f, "context_as_category")
    val trustedContext = list(f, "trusted_context")
    val trustedExtra = f.getInt("trusted_extra")
    val serverFreshS = f.getInt("server_fresh_s")

    companion object {
        fun parse(json: String) = FusionConfig(JSONObject(json))
    }
}

private fun JSONArray.strings(): Set<String> = (0 until length()).map { getString(it) }.toSet()

fun fuse(
    cues: CueResult,
    rules: Rules,
    f: FusionConfig,
    context: Set<String> = emptySet(),
    judge: Judge? = null,
    server: Verdict? = null,
    user: Boolean = false,
    prev: String = "none",
): Verdict {
    val cats = (cues.categories.toSet() - "discussion") + (context intersect f.contextAsCategory)
    val strong = cats - rules.weak
    val extra = if ((context intersect f.trustedContext).isNotEmpty()) f.trustedExtra else 0
    val j = judge?.takeIf { !it.abstain }
    val sources = mutableSetOf<String>()
    var level = "none"

    if (cats.size >= f.watchMin) {
        level = "watch"
        sources += "cues"
    }

    val warnCues = strong.size >= f.warnMinStrong + extra
    val warnLlm = j != null && j.pScam >= f.warnLlmP && cats.size >= f.warnLlmMinCats
    val warnCtx = context intersect f.warnContextAlone
    if (warnCues || warnLlm || warnCtx.isNotEmpty()) {
        level = "warn"
        if (warnLlm) sources += "phone_ai"
        if (warnCtx.isNotEmpty()) sources += if ("caller_check_failed" in warnCtx) "caller_check" else "context"
    }

    val scamCues = cats.size >= f.scamCuesMin + extra &&
        (!f.scamCuesNeedAction || (cats intersect rules.action).isNotEmpty()) &&
        (!f.scamCuesNeedType || cues.type != "unknown") &&
        !(f.scamDiscussionBlocks && cues.discussion)
    val scamLlm = j != null && j.pScam >= f.scamLlmP && cats.size >= f.scamLlmMinCats
    val strongCtx = context intersect f.strongContext
    // two independent kinds of evidence: what was said (cues or the judge) and what the phone saw
    val scamCtx = strongCtx.isNotEmpty() && (warnCues || warnLlm)
    if (scamCues || scamLlm || scamCtx || user) {
        level = "scam"
        if (scamCtx) sources += if ("caller_check_failed" in strongCtx) "caller_check" else "context"
        if (scamLlm) sources += "phone_ai"
        if (user) sources += "user"
    }

    var kind = cues.type
    if (kind == "unknown" && j != null && j.type != "unknown") kind = j.type
    if (kind == "unknown" && "caller_check_failed" in context) kind = "impersonation"

    if (server != null) {
        // the server heard the same call with a stronger model and the same context: it decides,
        // except that the user's own "Alert family" always stands
        level = higher(server.level, if (user) "scam" else "none")
        if (server.type != "unknown") kind = server.type
        sources += server.sources + "server"
    }
    level = higher(level, prev)
    return Verdict(level, kind, cats.sorted(), sources.sorted())
}
