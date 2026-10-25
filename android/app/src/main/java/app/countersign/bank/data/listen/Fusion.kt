package app.countersign.bank.data.listen

import app.countersign.bank.data.Reason
import app.countersign.bank.data.Risk
import app.countersign.bank.data.RiskLevel
import app.countersign.bank.data.RiskSource
import app.countersign.bank.data.ScamType
import org.json.JSONArray
import org.json.JSONObject

/*
 * Fusion: cues, our scam classifier, context signals and the voice check → one level.
 * Rules: assets/fusion.json. Port of engine/listener/fusion.py; keep the two identical.
 * Levels never go down during a call.
 */

val LEVELS = listOf("none", "watch", "warn", "scam")

/** Talk about scams, a real caller's warning: never evidence of a scam. */
val NOT_CUES = setOf("discussion", "protective")

/** What a warning mentions ("never share your OTP", "kisi ko mat batana"): not counted when the caller is warning. */
val WARNED = setOf("credentials", "secrecy")

fun higher(a: String, b: String) = if (LEVELS.indexOf(a) >= LEVELS.indexOf(b)) a else b

/** What the scam classifier (ScamClassifier.kt) said about the transcript so far. */
data class Judge(val pScam: Double, val type: String = "unknown", val abstain: Boolean = false)

data class Verdict(
    val level: String,
    val type: String,
    val cues: List<String>,
    val sources: List<String>,
    /** `scam` from the cue words alone (one source): the hybrid wants a second one (Hybrid.kt). */
    val alone: Boolean = false,
) {
    fun toRisk(since: Long, reason: Reason? = null) = Risk(
        level = RiskLevel.entries.first { it.wire == level },
        type = ScamType.entries.firstOrNull { it.wire == type } ?: ScamType.UNKNOWN,
        cues = cues,
        sources = sources.mapNotNull { s -> RiskSource.entries.firstOrNull { it.wire == s } }.toSet(),
        since = since,
        reason = reason,
    )
}

class FusionConfig(private val f: JSONObject) {
    private fun list(o: JSONObject, k: String): Set<String> = o.getJSONArray(k).strings()
    val watchMin = f.getJSONObject("watch").getInt("min_categories")
    private val w = f.getJSONObject("warn")
    val warnMinStrong = w.getInt("min_strong")
    val warnClfP = w.getDouble("clf_p")
    val warnClfMinCats = w.getInt("clf_min_categories")
    val warnClfVetoBelow = w.getDouble("clf_veto_below")
    val warnContextAlone = list(w, "context_alone")
    private val s = f.getJSONObject("scam")
    val scamCuesMin = s.getInt("cues_min_categories")
    val scamCuesNeedAction = s.getBoolean("cues_need_action")
    val scamCuesNeedType = s.getBoolean("cues_need_type")
    val scamDiscussionBlocks = s.getBoolean("discussion_blocks_cues")
    val scamClfP = s.getDouble("clf_p")
    val scamClfMinCats = s.getInt("clf_min_categories")
    val scamClfNeedsCueWarn = s.getBoolean("clf_needs_cue_warn")
    val strongContext = list(s, "strong_context")
    val contextAsCategory = list(f, "context_as_category")
    val trustedContext = list(f, "trusted_context")
    val trustedExtra = f.getInt("trusted_extra")
    val llmCanRaise = f.optJSONObject("llm")?.optBoolean("can_raise", true) ?: true

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
    val protective = "protective" in cues.categories
    val talk = cues.categories.toSet() - NOT_CUES - (if (protective) WARNED else emptySet())
    val cats = talk + (context intersect f.contextAsCategory)
    val strong = cats - rules.weak
    val extra = if ((context intersect f.trustedContext).isNotEmpty()) f.trustedExtra else 0
    val j = judge?.takeIf { !it.abstain }
    val sources = mutableSetOf<String>()
    var level = "none"

    if (cats.size >= f.watchMin) {
        level = "watch"
        sources += "cues"
    }

    val vetoed = j != null && j.pScam < f.warnClfVetoBelow // the classifier is sure it's harmless
    val warnCues = strong.size >= f.warnMinStrong + extra && !vetoed
    // the same, from what was said only: a context signal that already counts on its own must not count twice
    val warnSaid = (talk - rules.weak).size >= f.warnMinStrong + extra && !vetoed
    val warnClf = j != null && j.pScam >= f.warnClfP && cats.size >= f.warnClfMinCats
    val warnCtx = context intersect f.warnContextAlone
    if (warnCues || warnClf || warnCtx.isNotEmpty()) {
        level = "warn"
        if ("synthetic_voice" in context) sources += "voice"
        if (warnClf) sources += "phone_ai"
        if ("caller_check_failed" in warnCtx) sources += "caller_check"
        if ("synthetic_voice" in warnCtx) sources += "voice"
        if ((warnCtx - setOf("caller_check_failed", "synthetic_voice")).isNotEmpty()) sources += "context"
    }

    val strongCtx = context intersect f.strongContext
    val scamCues = (cats - strongCtx).size >= f.scamCuesMin + extra &&
        (!f.scamCuesNeedAction || (cats intersect rules.action).isNotEmpty()) &&
        (!f.scamCuesNeedType || cues.type != "unknown") &&
        !(f.scamDiscussionBlocks && (cues.discussion || protective))
    val scamClf = j != null && j.pScam >= f.scamClfP && cats.size >= f.scamClfMinCats &&
        (!f.scamClfNeedsCueWarn || warnSaid) &&
        !(f.scamDiscussionBlocks && (cues.discussion || protective))
    // two independent kinds of evidence: what was said (cues or the classifier) and what the phone saw; the phone's
    // signal counts once, so it can't also be one of the cues that made the warn
    val scamCtx = strongCtx.isNotEmpty() && (warnSaid || warnClf)
    if (scamCues || scamClf || scamCtx || user) {
        level = "scam"
        if (scamCtx) sources += if ("caller_check_failed" in strongCtx) "caller_check" else "context"
        if (scamClf) sources += "phone_ai"
        if (user) sources += "user"
    }

    var kind = cues.type
    if (kind == "unknown" && j != null && j.type != "unknown") kind = j.type
    if (kind == "unknown" && "caller_check_failed" in context) kind = "impersonation"

    var all = cats
    var alone = level == "scam" && !(scamClf || scamCtx || user)
    if (server != null && server.level != "none") {
        // the server's stronger check heard the same call: it can raise the level, never lower it
        level = higher(level, server.level)
        if (kind == "unknown" && server.type != "unknown") kind = server.type
        sources += "server"
        all = cats + (server.cues.toSet() - NOT_CUES)
        alone = alone && server.level != "scam"
    }
    level = higher(level, prev)
    return Verdict(level, kind, all.sorted(), sources.sorted(), alone)
}
