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
 * Two judges (Hybrid.kt): the conversation check (Conversation.kt, with the model pack: [conv] set), from what the
 * caller is doing over the call, and the cue rules through fusion (with our small classifier in basic mode). The
 * smarter check (LlmCheck, optional) and the user add to them; `scam` needs two independent sources.
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
        private val tokens = ArrayList<String>()
        private var context = emptySet<String>()
        private var voice: Float? = null
        private var server: Verdict? = null
        private var llm: LlmVerdict? = null
        private var user = false
        private var prev = "none"

        /** The user said "Not a scam": nothing more for this call. */
        var cleared = false
            private set

        var verdict: Verdict = Verdict("none", "unknown", emptyList(), emptyList())
            private set

        var judge: Judge? = null
            private set

        /** The smarter check's verdict whose reason the card shows, or null. */
        var shown: LlmVerdict? = null
            private set

        /** The signals as the judges saw them: the phone's, the voice check's and those derived from the words. */
        var signals: Set<String> = emptySet()
            private set

        /** One recognised segment. Pass every hypothesis (Hindi and English models) as separate calls. */
        fun feed(text: String): Verdict {
            if (text.isBlank()) return verdict
            if (cleared) return verdict
            convCall?.feed(text)
            scorer.feed(text)
            tokens.addAll(normalize(text))
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

        /** The smarter check's latest answer (LlmCheck): `scam` at warn makes scam; `ok` / `unsure` never lower it. */
        fun llm(v: LlmVerdict?): Verdict {
            llm = v
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
            shown = null
        }

        val transcript: String get() = words.toString()

        private fun update(): Verdict {
            if (cleared) return verdict
            val cues = scorer.result()
            val said = cues.categories.toSet() + convCall?.reasons.orEmpty()
            val ctx = derivedContext(signals(context, voice), tokens, said)
            signals = ctx
            val c = if (convCall != null) {
                convCall.context(ctx)
                judge = convCall.lastP?.let { Judge(it) }
                combine(fuse(cues, rules, fusion, ctx), convCall.verdict(), convCall.modelLevel, llm, server, user, prev, fusion.llmCanRaise)
            } else {
                judge = clf.judge(transcript, clf.minWordsCall)
                combine(fuse(cues, rules, fusion, ctx, judge), null, "none", llm, server, user, prev, fusion.llmCanRaise)
            }
            verdict = c.verdict
            shown = c.shown
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
            val c = Call()
            c.context(ctx0)
            val segs = textSegments(text)
            for (s in segs) c.feed(s)
            var v = c.verdict
            // a whole message or recording is all the evidence there will be: judged once more as a whole
            val whole = if (segs.isEmpty()) 0.0 else conv.models.p(convWindow(segs))
            if (whole >= conv.cfg.main.scam && v.level == "warn") v = v.copy(level = "scam")
            return toAnalysis(v, c.judge, c.signals, voiceClone, text, seconds)
        }
        val cues = CallScorer(rules).feed(text)
        val j = clf.judge(text, minWords)
        val ctx = derivedContext(ctx0, normalize(text), cues.categories.toSet())
        return toAnalysis(fuse(cues, rules, fusion, ctx, j), j, ctx, voiceClone, text, seconds)
    }

    companion object {
        const val SYNTHETIC_VOICE = "synthetic_voice"

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
