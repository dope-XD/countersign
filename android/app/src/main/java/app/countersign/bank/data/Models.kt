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
    /** Listen to calls and warn about scams (the call listener). */
    val listenCalls: Boolean = true,
    /** Also send call audio to the bank's own server for a stronger check, when it's reachable. */
    val strongerCheck: Boolean = true,
    /** Text family from this phone's SIM if their app is offline when a scam call is detected. */
    val smsFallback: Boolean = true,
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

/** A scam call is (or just was) going on: the pay guard is on until [until]. [reason]: not_them, not_with_you or ring_no. */
data class Scam(val checkId: String, val memberId: String, val label: String, val reason: String, val until: Long)

enum class ApprovalKind(val wire: String) { CALL_CHECK("call_check"), BANK_CALL("app_approval") }

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
    /** Whether the call listener can hear this call. */
    val listen: ListenState = ListenState.OFF,
    val onSpeaker: Boolean = false,
    /** How much this call looks like a scam, from everything the listener has heard and seen so far. */
    val risk: Risk? = null,
)

/* ---- the call listener (docs/agents/CONTRACT.md, "Call listener") ---- */

enum class ListenState {
    /** Not a call, or the user turned listening off. */
    OFF,

    /** Mic and accessibility not granted. */
    NO_PERMISSION,

    /** The speech model hasn't been downloaded and the server isn't reachable. */
    NO_MODEL,

    /** Can hear only this phone's owner: ask for speaker. */
    NEED_SPEAKER,
    LISTENING,
}

/** none < watch (keep quiet) < warn (amber card) < scam (red card, family alarmed, pay guard on). */
enum class RiskLevel(val wire: String) { NONE("none"), WATCH("watch"), WARN("warn"), SCAM("scam") }

enum class ScamType(val wire: String) {
    DIGITAL_ARREST("digital_arrest"),
    BANK_KYC("bank_kyc"),
    OTP_UPI("otp_upi"),
    REMOTE_ACCESS("remote_access"),
    FAMILY_EMERGENCY("family_emergency"),
    COURIER_CUSTOMS("courier_customs"),
    TRAI_SIM("trai_sim"),
    JOB_TASK("job_task"),
    INVESTMENT("investment"),
    REWARD("reward"),

    /** The caller check said this isn't the family member's phone. */
    IMPERSONATION("impersonation"),
    UNKNOWN("unknown"),
}

/** Where the evidence came from. `scam` always needs at least two of these (or USER). */
enum class RiskSource(val wire: String) {
    CUES("cues"),
    PHONE_AI("phone_ai"),
    SERVER("server"),
    CONTEXT("context"),
    CALLER_CHECK("caller_check"),
    USER("user"),
}

data class Risk(
    val level: RiskLevel,
    val type: ScamType,
    /** Cue and context ids that fired, e.g. "authority", "secrecy", "remote_app_opened" (scam_patterns.json). */
    val cues: List<String>,
    val sources: Set<RiskSource>,
    /** When this level was first reached. */
    val since: Long,
)

enum class ModelStatus { NOT_NEEDED, MISSING, DOWNLOADING, READY, FAILED }

/** The on-phone speech model for the app's language. */
data class ModelState(val status: ModelStatus, val progress: Float = 0f, val sizeMb: Int = 0)

/** Everything the app asks for, in the order onboarding shows them. */
enum class Permission {
    PHONE,
    CALL_SCREENING,
    CALL_REDIRECTION,

    /** PROCESS_OUTGOING_CALLS: the number this phone dials, for the caller check (replaces CALL_REDIRECTION). */
    OUTGOING_CALLS,
    MICROPHONE,

    /** The call listener's accessibility service (Android 13+ sideloads first need "Allow restricted settings"). */
    ACCESSIBILITY,
    SMS,
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

    /** A family member's phone thinks they're on a scam call right now. */
    data class FamilyAlarm(val memberId: String, val label: String, val type: ScamType, val at: Long) : AppEvent
}

/* ---- state for the two overlay composables C shows from a service (docs/agents/ui.md) ---- */

/**
 * The card over the dialer.
 * - [caller] and [check] null: an unknown number, so show the "Says they're family? Check" chip and the faces in [family].
 * - [check] set: show its verdict and, on DANGER or UNKNOWN, Ring / Call [check]'s member.
 */
data class CallCheckUi(
    val caller: Member?,
    val check: Check?,
    val family: List<Member>,
    val listen: ListenState = ListenState.OFF,
    val onSpeaker: Boolean = false,
    /** Show the amber card at WARN and the red one at SCAM, next to the caller check's verdict. */
    val risk: Risk? = null,
)

/** The full-screen alarm on a family member's phone: "Mummy may be on a scam call". */
data class FamilyAlarmUi(val memberId: String, val label: String, val type: ScamType, val at: Long)

/** The red screen over a payment app while [scam] is on. */
data class PayGuardUi(val scam: Scam, val appName: String?)
