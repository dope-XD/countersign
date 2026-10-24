package app.countersign.bank.data

/*
 * The app's data, as the screens see it (docs/agents/CONTRACT.md).
 * Contract file: only agent A edits it, through a contract-change issue.
 * Times are epoch milliseconds. Parsing from JSON lives in RealRepository.
 */

enum class Lang(val code: String) { EN("en"), HI("hi") }

/** How a family check reaches this phone. */
enum class CheckChannel(val wire: String) { RING("ring"), NOTIFY("notify") }

data class Me(
    val id: String,
    val name: String,
    val mobile: String,
    val lang: Lang,
    val channel: CheckChannel,
    val shareCallStatus: Boolean,
)

data class Member(
    val id: String,
    /** What I call them: "Rahul", "Mummy". */
    val label: String,
    val name: String,
    val mobile: String,
    val since: Long,
    val online: Boolean,
    /** Linked under 24 hours ago: such a link can stop a payment but can't give a ✓ Verified. */
    val newLink: Boolean,
) {
    val initials: String get() = label.split(' ').filter { it.isNotBlank() }.take(2).joinToString("") { it.take(1).uppercase() }
}

data class JoinRequest(val customerId: String, val name: String, val label: String)

enum class Verdict(val wire: String) {
    CHECKING("checking"),
    VERIFIED("verified"),
    LIKELY("likely"),
    NOT_WITH_YOU("not_with_you"),
    NOT_THEM("not_them"),
    CANT_REACH("cant_reach"),
}

enum class RingState(val wire: String) { NONE("none"), RINGING("ringing"), YES("yes"), NO("no"), NO_ANSWER("no_answer") }

/** What the user should take from a check, after the ring (if any) has been answered. */
enum class Outcome { PENDING, SAFE, DANGER, UNKNOWN }

data class Check(
    val id: String,
    val callId: String,
    val memberId: String,
    val label: String,
    val verdict: Verdict,
    val numberMatched: Boolean,
    /** The caller showed this member's number, but their phone isn't calling: caller ID may be faked. */
    val spoofSuspected: Boolean,
    val ring: RingState,
    val createdAt: Long,
    val decidedAt: Long?,
) {
    val outcome: Outcome
        get() = when {
            ring == RingState.YES -> Outcome.SAFE
            ring == RingState.NO -> Outcome.DANGER
            ring == RingState.RINGING || verdict == Verdict.CHECKING -> Outcome.PENDING
            verdict == Verdict.VERIFIED || verdict == Verdict.LIKELY -> Outcome.SAFE
            verdict == Verdict.NOT_WITH_YOU || verdict == Verdict.NOT_THEM -> Outcome.DANGER
            else -> Outcome.UNKNOWN
        }
}

/** A scam call is (or just was) going on: the pay guard is on until [until]. */
data class Scam(val checkId: String, val memberId: String, val label: String, val reason: Verdict, val until: Long)

enum class ApprovalKind(val wire: String) { CALL_CHECK("call_check"), BANK_CALL("bank_call") }

/** A question for this phone's owner: the ring screen. "Yes" needs the fingerprint or screen lock. */
data class Approval(
    val id: String,
    val kind: ApprovalKind,
    /** Who's asking, as this phone calls them: "Mummy". */
    val from: String,
    val question: String,
    val detail: String,
    val challenge: String,
    val channel: CheckChannel,
    val expiresAt: Long,
    val status: String,
)

data class Home(
    val me: Me,
    val family: List<Member>,
    val joinRequests: List<JoinRequest>,
    val approvals: List<Approval>,
    /** Newest first, at most 10. */
    val checks: List<Check>,
    val scam: Scam?,
)

data class Invite(val code: String, val expiresAt: Long, val qr: String)

/** The call on this phone right now, as Countersign sees it. */
data class LiveCall(
    val id: String,
    val incoming: Boolean,
    val answered: Boolean,
    /** The family member whose saved number this is, or null for any other number. */
    val caller: Member?,
    val check: Check?,
)

/** Everything the app asks for, in the order onboarding shows them. */
enum class Permission {
    PHONE,
    CALL_SCREENING,
    CALL_REDIRECTION,
    NOTIFICATIONS,
    OVERLAY,
    USAGE_ACCESS,
    FULL_SCREEN,
    BATTERY,
}

data class Permissions(val granted: Set<Permission>) {
    val missing: List<Permission> get() = Permission.entries.filter { it !in granted }

    /** What the app can't work without; the rest makes it better. */
    val essentialsOk: Boolean get() = listOf(Permission.PHONE, Permission.NOTIFICATIONS, Permission.OVERLAY).all { it in granted }
}

sealed interface AppEvent {
    /** Someone called [by] showing my number, and my phone wasn't calling them. */
    data class SpoofAlert(val by: String, val at: Long) : AppEvent

    data class FamilyRequest(val customerId: String, val name: String) : AppEvent

    data class FamilyJoined(val customerId: String, val name: String) : AppEvent

    data class Error(val message: String) : AppEvent
}

/* ---- state for the two overlay composables C shows from a service (docs/agents/ui.md) ---- */

/**
 * The card over the dialer.
 * - [caller] and [check] null: an unknown number, so show the "Says they're family? Check" chip and the faces in [family].
 * - [check] set: show its verdict and, on DANGER or UNKNOWN, Ring / Call [check]'s member.
 */
data class CallCheckUi(val caller: Member?, val check: Check?, val family: List<Member>)

/** The red screen over a payment app while [scam] is on. */
data class PayGuardUi(val scam: Scam, val appName: String?)
