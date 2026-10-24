package app.countersign.bank

import android.content.Context
import android.util.Log
import app.countersign.bank.data.RealRepository
import app.countersign.bank.data.Repo
import app.countersign.bank.data.Risk
import app.countersign.bank.data.listen.CallScorer
import app.countersign.bank.data.listen.CueResult
import app.countersign.bank.data.listen.FusionConfig
import app.countersign.bank.data.listen.Rules
import app.countersign.bank.data.listen.Verdict
import app.countersign.bank.data.listen.fuse

/**
 * How much one call looks like a scam: everything the listener knows about it, run through A's
 * [fuse] (assets/fusion.json).
 *
 * - the words heard on the phone ([heard], from the on-phone speech-to-text, #42);
 * - the context signals ([context], #40), e.g. "unknown_number", "caller_check_failed";
 * - the server's stronger check ([server], from [ListenStream]);
 * - the user pressing "Alert family" ([alertFamily]).
 *
 * The level never goes down during a call, and a server verdict stops counting once it's older
 * than `server_fresh_s` (the socket dropped). [Companion] holds the call going on now.
 */
class CallRisk(private val rules: Rules, private val config: FusionConfig, private val clock: () -> Long = System::currentTimeMillis) {
    private val scorer = CallScorer(rules)
    private var cues = CueResult(emptyList(), "unknown", emptyMap())
    private var serverVerdict: Verdict? = null
    private var serverAt = 0L
    private var user = false
    private var level = "none"
    private var since = 0L

    var signals: Set<String> = emptySet()
        private set

    fun heard(text: String) {
        cues = scorer.feed(text)
    }

    fun context(now: Set<String>) {
        signals = now
    }

    fun server(v: Verdict) {
        serverVerdict = v
        serverAt = clock()
    }

    fun alertFamily() {
        user = true
    }

    /** The risk now, or null while the call looks fine. */
    fun risk(): Risk? {
        val fresh = serverVerdict?.takeIf { clock() - serverAt <= config.serverFreshS * 1000L }
        val v = fuse(cues, rules, config, context = signals, server = fresh, user = user, prev = level)
        if (v.level != level) {
            level = v.level
            since = clock()
        }
        return if (level == "none") null else v.toRisk(since)
    }

    companion object {
        private const val TAG = "CallRisk"
        private var rules: Rules? = null
        private var config: FusionConfig? = null
        private var callId: String? = null
        private var current: CallRisk? = null

        fun load(c: Context) {
            if (rules != null) return
            rules = Rules.parse(c.assets.open("scam_patterns.json").bufferedReader().use { it.readText() })
            config = FusionConfig.parse(c.assets.open("fusion.json").bufferedReader().use { it.readText() })
        }

        /** A new call (or none): forget everything about the last one. */
        @Synchronized
        fun reset(call: String?) {
            if (call == callId) return
            callId = call
            val r = rules
            val f = config
            current = if (call != null && r != null && f != null) CallRisk(r, f) else null
        }

        /** The current call's signals, for the server's `context` message. */
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
            (Repo.instance as? RealRepository)?.setRisk(id, risk)
        }
    }
}
