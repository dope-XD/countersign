package app.countersign.bank.data.listen

import app.countersign.bank.data.Analysis
import app.countersign.bank.data.Risk
import app.countersign.bank.data.RiskLevel
import app.countersign.bank.data.RiskSource
import app.countersign.bank.data.ScamType

/*
 * Everything the phone knows about a call or a message → one verdict. Used by the live call listener (one [Call] per
 * call) and by "Check a recording or message" ([text]). Pure Kotlin, no Android: AnalyzerTest runs it on the JVM.
 * Port of engine/listener/analyzer.py; keep the two identical.
 *
 * With the model pack ([conv] set): the conversation check (Conversation.kt) decides, from what the caller is doing
 * over the call, not from words. Without it, basic mode: the cue scorer and our small classifier, through fusion.
 */
class Analyzer(
    private val rules: Rules,
    private val fusion: FusionConfig,
    private val clf: ScamClassifier,
    /** The voice-clone score at or above which the caller's voice counts as AI-made (the voice model's threshold). */
    private val voiceThreshold: Float = 0.5f,
    /** The conversation models, once the model pack is installed; null = basic mode. */
    private val conv: ConvKit? = null,
) {
    val basicMode: Boolean get() = conv == null

    /** One live call. Feed it speech-to-text segments, context and the voice score as they come; read [verdict]. */
    inner class Call {
        private val scorer = CallScorer(rules)
        private val convCall = conv?.let { ConvCall(it.models, it.matcher, it.cfg, rules) }
        private val words = StringBuilder()
        private var context = emptySet<String>()
        private var voice: Float? = null
        private var server: Verdict? = null
        private var user = false
        private var prev = "none"

        /** The user said "Not a scam": nothing more for this call. */
        var cleared = false
            private set

        var verdict: Verdict = Verdict("none", "unknown", emptyList(), emptyList())
            private set

        var judge: Judge? = null
            private set

        /** One recognised segment. Pass every hypothesis (Hindi and English models) as separate calls. */
        fun feed(text: String): Verdict {
            if (text.isBlank()) return verdict
            if (cleared) return verdict
            if (convCall != null) convCall.feed(text) else scorer.feed(text)
            if (words.isNotEmpty()) words.append(' ')
            words.append(text)
            return update()
        }

        fun context(signals: Set<String>): Verdict {
            context = signals
            return update()
        }

        /** The voice-clone model's score on the caller's first ~20 s of speech. */
        fun voice(score: Float?): Verdict {
            voice = score
            return update()
        }

        /** The server's stronger check (ListenStream): it can raise the level, never lower it. */
        fun server(v: Verdict): Verdict {
            server = v
            return update()
        }

        /** "Alert family" on the card. */
        fun alert(): Verdict {
            user = true
            return update()
        }

        fun clear() {
            cleared = true
            verdict = Verdict("none", verdict.type, verdict.cues, listOf("user"))
        }

        val transcript: String get() = words.toString()

        private fun update(): Verdict {
            if (cleared) return verdict
            verdict = if (convCall != null) {
                convCall.context(signals(context, voice))
                judge = convCall.lastP?.let { Judge(it) }
                withServerAndUser(convCall.verdict(), server, user, prev)
            } else {
                judge = clf.judge(transcript, clf.minWordsCall)
                fuse(scorer.result(), rules, fusion, signals(context, voice), judge, server, user, prev)
            }
            prev = verdict.level
            return verdict
        }
    }

    fun call() = Call()

    private fun signals(context: Set<String>, voice: Float?): Set<String> =
        if (voice != null && voice >= voiceThreshold) context + SYNTHETIC_VOICE else context

    /**
     * A whole transcript or message at once: "Check a recording or message". [voiceClone] is the voice score of a
     * recording (null for text). [minWords]: the classifier abstains under this many words.
     */
    fun text(
        text: String,
        context: Set<String> = emptySet(),
        voiceClone: Float? = null,
        seconds: Float = 0f,
        minWords: Int = clf.minWordsText,
    ): Analysis {
        val ctx0 = signals(context, voiceClone)
        if (conv != null) {
            val c = ConvCall(conv.models, conv.matcher, conv.cfg, rules)
            c.context(ctx0)
            var v = c.verdict()
            for (s in textSegments(text)) v = c.feed(s)
            // a whole message or recording is all the evidence there will be: judged once more as a whole
            val whole = conv.models.p(convWindow(textSegments(text)))
            if (whole >= conv.cfg.main.scam && v.level != "scam" && LEVELS.indexOf(v.level) >= LEVELS.indexOf("warn")) {
                v = v.copy(level = "scam")
            }
            return toAnalysis(v, c.lastP?.let { Judge(it) }, ctx0, voiceClone, text, seconds)
        }
        val cues = CallScorer(rules).feed(text)
        val j = clf.judge(text, minWords)
        val ctx = signals(context, voiceClone)
        return toAnalysis(fuse(cues, rules, fusion, ctx, j), j, ctx, voiceClone, text, seconds)
    }

    companion object {
        const val SYNTHETIC_VOICE = "synthetic_voice"

        /** The server's stronger check can raise the level, never lower it; "Alert family" makes it scam. */
        fun withServerAndUser(v: Verdict, server: Verdict?, user: Boolean, prev: String): Verdict {
            var level = v.level
            var kind = v.type
            val sources = v.sources.toMutableSet()
            val cues = v.cues.toMutableList()
            if (server != null && server.level != "none") {
                level = higher(level, server.level)
                if (kind == "unknown") kind = server.type
                sources.add("server")
                server.cues.filter { it != "discussion" && it !in cues }.forEach(cues::add)
            }
            if (user) {
                level = "scam"; sources.add("user")
            }
            return Verdict(higher(level, prev), kind, cues, sources.sorted())
        }

        fun toAnalysis(v: Verdict, j: Judge?, context: Set<String>, voiceClone: Float?, transcript: String, seconds: Float): Analysis {
            val r: Risk = v.toRisk(0)
            // "why it fired": cue categories, then the context signals that count as evidence
            val why = (v.cues + context.filter { it == SYNTHETIC_VOICE || it in EVIDENCE }).distinct()
            return Analysis(
                level = r.level,
                type = if (r.level == RiskLevel.NONE) ScamType.UNKNOWN else r.type,
                pScam = j?.takeIf { !it.abstain }?.pScam?.toFloat(),
                cues = why,
                sources = r.sources.filter { it != RiskSource.USER || v.level == "scam" }.toSet(),
                voiceClone = voiceClone,
                transcript = transcript,
                seconds = seconds,
            )
        }

        private val EVIDENCE = setOf("remote_app_opened", "caller_check_failed", "video_call_unknown", "international_number", "long_call")
    }
}
