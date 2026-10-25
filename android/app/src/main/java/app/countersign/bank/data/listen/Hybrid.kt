package app.countersign.bank.data.listen

/*
 * The two judges together (CONTRACT.md, "Call listener"): the conversation check (with the model pack) and the cue
 * rules through fusion (with our small classifier in basic mode), plus the smarter check, the user and the server.
 * - watch / warn: the higher of the two judges.
 * - scam needs two independent sources: a judge at scam from what was said alone plus another source at warn or above
 *   (the other judge, the smarter check), or a judge that already paired what was said with what the phone saw, or the
 *   call at warn plus the smarter check saying scam. Basic mode: the cue rules' own scam stands, as before.
 * Pure Kotlin. Port of engine/listener/hybrid.py; keep the two identical (HybridTest, hybrid_vectors.json).
 */

private val BANK_CLAIM = setOf("authority", "verification_pretext") // claims to be police, a court or a bank, from an unknown number that isn't 1600-series
private val TRUSTED = setOf("known_contact", "caller_verified")
private val PHONE = setOf("context", "caller_check", "voice")

/*
 * The scam's own playbook, said outright: an ask for the code or money, to this person, under secrecy or a threat.
 * Genuine callers don't say all of it (ml/eval/hybrid_eval.py: no false red on any genuine set), so it stands alone.
 */
private val ASKED = setOf("direct_ask")
private val TAKES = setOf("credentials", "money_ask", "remote_access")
private val PRESSES = setOf("secrecy", "threat")

fun playbook(cues: List<String>): Boolean = cues.any { it in ASKED } && cues.any { it in TAKES } && cues.any { it in PRESSES }

fun atLeast(level: String, floor: String) = LEVELS.indexOf(level) >= LEVELS.indexOf(floor)

/** Signals the phone derives from the words: [said] is the cue categories and the conversation's moves so far. */
fun derivedContext(context: Set<String>, tokens: List<String>, said: Set<String>): Set<String> {
    val out = context.toMutableSet()
    val unknown = "unknown_number" in out || ("video_call_unknown" in out && out.none { it in TRUSTED })
    if (unknown && digitsReadOut(tokens)) out += "digits_read_out"
    if ("unknown_number" in out && "series_1600" !in out && said.any { it in BANK_CLAIM }) out += "bank_claim_not_1600"
    return out
}

/** The verdict, and the smarter check's verdict whose reason the card shows (null when it isn't shown). */
data class Combined(val verdict: Verdict, val shown: LlmVerdict?)

/**
 * [cue]: fuse() without server, user or prev. [conv]: the conversation check's verdict, [convModel] its model's own
 * level (what was said only); null in basic mode.
 */
fun combine(
    cue: Verdict,
    conv: Verdict? = null,
    convModel: String = "none",
    llm: LlmVerdict? = null,
    server: Verdict? = null,
    user: Boolean = false,
    prev: String = "none",
    llmCanRaise: Boolean = true,
): Combined {
    fun cap(x: String) = if (x == "scam") "warn" else x

    var level = cap(cue.level)
    if (conv != null) {
        // cue words alone are not enough for amber while the conversation model hears nothing of a scam (genuine bank
        // and courier calls use the same words), unless they are strong enough for their own red; a phone signal still is
        if (level == "warn" && cue.level != "scam" && convModel == "none" && cue.sources.none { it in PHONE }) level = "watch"
        level = higher(level, cap(conv.level))
    }
    val llmScam = llm?.verdict == "scam"
    val raiseLlm = llmScam && llmCanRaise
    var red = if (conv == null) {
        cue.level == "scam" // basic mode: the cue rules' own scam, as before
    } else {
        val convSaid = convModel == "scam"
        val convPaired = conv.level == "scam" && !convSaid // the conversation at warn + a strong phone signal
        val cuePaired = cue.level == "scam" && !cue.alone
        convPaired || cuePaired ||
            (convSaid && (atLeast(cue.level, "warn") || raiseLlm)) ||
            (cue.level == "scam" && cue.alone && (atLeast(convModel, "watch") || raiseLlm || playbook(cue.cues)))
    }
    red = red || (raiseLlm && atLeast(level, "warn"))
    if (red) level = "scam"

    val sources = (cue.sources + (conv?.sources ?: emptyList())).toMutableSet()
    if (llmScam && atLeast(level, "warn")) sources += "llm"
    var kind = if (conv != null && conv.type != "unknown") conv.type else cue.type
    if (kind == "unknown" && llmScam && llm!!.type != "unknown") kind = llm.type
    val cues = (conv?.cues ?: emptyList()).toMutableList()
    cue.cues.filter { it !in cues }.forEach(cues::add)

    if (server != null && server.level != "none") {
        level = higher(level, server.level)
        if (kind == "unknown") kind = server.type
        sources += "server"
        server.cues.filter { it != "discussion" && it !in cues }.forEach(cues::add)
    }
    if (user) {
        level = "scam"
        sources += "user"
    }
    level = higher(level, prev)
    val shown = if (llmScam && atLeast(level, "warn")) llm else null
    return Combined(Verdict(level, kind, cues, sources.sorted()), shown)
}
