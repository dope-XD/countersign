package app.countersign.bank

import android.content.Context
import android.util.Log
import app.countersign.bank.data.RealRepository
import app.countersign.bank.data.Repo
import app.countersign.bank.data.Risk
import app.countersign.bank.data.listen.Analyzer
import app.countersign.bank.data.listen.FusionConfig
import app.countersign.bank.data.listen.Rules
import app.countersign.bank.data.listen.ScamClassifier

/**
 * How much the call going on now looks like a scam: one [Analyzer.Call] per call, fed by the on-phone
 * speech-to-text ([heard]), the context signals ([CallContext]), the voice-clone check ([voice]) and the
 * user ("Alert family", "Not a scam"). Everything stays on the phone; the result goes to [app.countersign.bank.data.LiveCall.risk].
 */
class CallRisk(analyzer: Analyzer, private val clock: () -> Long = System::currentTimeMillis) {
    private val call = analyzer.call()
    private var since = 0L
    private var level = "none"

    var signals: Set<String> = emptySet()
        private set

    fun heard(text: String) {
        call.feed(text)
    }

    fun context(now: Set<String>) {
        signals = now
        call.context(now)
    }

    fun voice(score: Float?) {
        call.voice(score)
    }

    fun alertFamily() {
        call.alert()
    }

    fun clear() = call.clear()

    val cleared get() = call.cleared

    /** The risk now, or null while the call looks fine (or the user said it's not a scam). */
    fun risk(): Risk? {
        val v = call.verdict
        if (v.level != level) {
            level = v.level
            since = clock()
        }
        return if (level == "none" || call.cleared) null else v.toRisk(since)
    }

    companion object {
        private const val TAG = "CallRisk"
        private var analyzer: Analyzer? = null
        private var callId: String? = null
        private var current: CallRisk? = null

        /** The phone's analyzer (cue rules, our classifier, fusion), also used by "Check a recording or message". */
        fun analyzer(c: Context): Analyzer {
            load(c)
            return analyzer!!
        }

        @Synchronized
        fun load(c: Context) {
            if (analyzer != null) return
            fun text(name: String) = c.assets.open(name).bufferedReader().use { it.readText() }
            val clf = ScamClassifier.load(c.assets.open("scam_clf.bin").use { it.readBytes() }, text("scam_clf.json"))
            analyzer = Analyzer(Rules.parse(text("scam_patterns.json")), FusionConfig.parse(text("fusion.json")), clf, VoiceCheck.threshold(c))
        }

        /** A new call (or none): forget everything about the last one. */
        @Synchronized
        fun reset(call: String?) {
            if (call == callId) return
            callId = call
            current = if (call != null) analyzer?.let { CallRisk(it) } else null
        }

        /** The current call's signals. */
        val signals: Set<String> @Synchronized get() = current?.signals.orEmpty()

        /** Changes the current call's risk and shows the result on [app.countersign.bank.data.LiveCall.risk]. */
        @Synchronized
        fun update(change: CallRisk.() -> Unit) {
            val r = current ?: return
            val id = callId ?: return
            val before = r.level
            r.change()
            val risk = r.risk()
            if (r.level != before) Log.i(TAG, "call is now ${r.level} (${risk?.type}, ${risk?.sources})")
            (Repo.instance as? RealRepository)?.setRisk(id, risk, r.cleared)
        }
    }
}
