package app.countersign.bank.data.listen

import app.countersign.bank.data.Analysis
import app.countersign.bank.data.Risk
import app.countersign.bank.data.RiskLevel
import app.countersign.bank.data.RiskSource
import app.countersign.bank.data.ScamType

/*
 * Everything the phone knows about a call or a message → one verdict: the cue scorer, our classifier,
 * context signals and the voice-clone score, through fusion. Used by the live call listener (one [Call] per call)
 * and by "Check a recording or message" ([text]). Pure Kotlin, no Android: AnalyzerTest runs it on the JVM.
 * Port of engine/listener/analyzer.py; keep the two identical.
 */
class Analyzer(
    private val rules: Rules,
    private val fusion: FusionConfig,
    private val clf: ScamClassifier,
    /** The voice-clone score at or above which the caller's voice counts as AI-made (the voice model's threshold). */
    private val voiceThreshold: Float = 0.5f,
) {
    /** One live call. Feed it speech-to-text segments, context and the voice score as they come; read [verdict]. */
    inner class Call {
        private val scorer = CallScorer(rules)
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
            scorer.feed(text)
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
            judge = clf.judge(transcript, clf.minWordsCall)
            verdict = fuse(scorer.result(), rules, fusion, signals(context, voice), judge, server, user, prev)
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
        val cues = CallScorer(rules).feed(text)
        val j = clf.judge(text, minWords)
        val ctx = signals(context, voiceClone)
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
