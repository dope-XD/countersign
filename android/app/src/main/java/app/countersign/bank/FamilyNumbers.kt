package app.countersign.bank

import android.os.SystemClock
import app.countersign.bank.data.Member

/**
 * The numbers of the calls on this phone, as CallScreener and CallRedirector see them, matched
 * against the family list by their last 10 digits. Only here, in memory: a raw number never
 * leaves the phone, only the member id it matched.
 */
object FamilyNumbers {
    private class Seen(val number: String, val at: Long)

    @Volatile private var incoming: Seen? = null

    @Volatile private var outgoing: Seen? = null

    /** A number older than this belongs to some other call. */
    private const val FRESH_MS = 15_000L

    fun last10(number: String?): String? = number?.filter(Char::isDigit)?.takeLast(10)?.takeIf { it.length == 10 }

    /** The family member whose saved number this is, or null. */
    fun match(number: String?, family: List<Member>): Member? {
        val n = last10(number) ?: return null
        return family.firstOrNull { last10(it.mobile) == n }
    }

    fun sawIncoming(number: String?) {
        incoming = number?.let { Seen(it, SystemClock.elapsedRealtime()) }
    }

    fun sawOutgoing(number: String?) {
        outgoing = number?.let { Seen(it, SystemClock.elapsedRealtime()) }
    }

    /** The number of the call that just rang or was just dialled, used once; null without the call roles. */
    fun takeIncoming(): String? = take(incoming).also { incoming = null }

    fun takeOutgoing(): String? = take(outgoing).also { outgoing = null }

    private fun take(s: Seen?) = s?.takeIf { SystemClock.elapsedRealtime() - it.at < FRESH_MS }?.number
}
