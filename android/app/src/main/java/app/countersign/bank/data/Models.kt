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
    /** Text family from this phone's SIM if their app is offline when a scam call is detected. */
    val smsFallback: Boolean = true,
)

/** Family, or work: a boss or colleague who might ask for a payment (the CEO-fraud case). */
enum class Circle(val wire: String) { FAMILY("family"), WORK("work") }

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
    val circle: Circle = Circle.FAMILY,
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
    /** The user said "Not a scam" / "I know this caller": risk is none and the listener stays quiet until the call ends. */
    val cleared: Boolean = false,
    /** The server's stronger check is listening too (only once the phone found the call suspicious). */
    val serverCheck: Boolean = false,
)

/* ---- the call listener (docs/agents/CONTRACT.md, "Call listener") ---- */

enum class ListenState {
    /** Not a call, or the user turned listening off. */
    OFF,

    /** Mic and accessibility not granted. */
    NO_PERMISSION,

    /** The model pack (speech-to-text + voice check) hasn't been downloaded yet. */
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

    /** "Your MD" in a meeting orders an urgent, secret payment to a new account (CEO fraud). */
    BOSS_PAYMENT("boss_payment"),

    /** The caller check said this isn't the family member's phone. */
    IMPERSONATION("impersonation"),
    UNKNOWN("unknown"),
}

/** Where the evidence came from. `scam` always needs at least two of these (or USER). */
enum class RiskSource(val wire: String) {
    /** Scam cue words (scam_patterns.json). */
    CUES("cues"),

    /** Our scam classifier on the transcript (data/listen/ScamClassifier.kt). */
    PHONE_AI("phone_ai"),

    /** The voice-clone model thinks the caller's voice is AI-made. Can raise warn, never scam on its own. */
    VOICE("voice"),

    /** The server's stronger check (laptop / bank server), asked only once the phone itself finds the call suspicious. */
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

/** The one model pack: on-phone speech-to-text (Hindi + English) and the voice-clone check. Downloaded once. */
data class ModelState(val status: ModelStatus, val progress: Float = 0f, val sizeMb: Int = 0)

/** Why the user said a warn or scam card was wrong. */
enum class FalseAlarmReason(val wire: String) { KNOW_CALLER("know_caller"), NOT_A_SCAM("not_a_scam") }

/**
 * "Check a recording or message": the same on-phone pipeline as a live call, on a file or pasted text.
 * Nothing leaves the phone.
 */
data class Analysis(
    val level: RiskLevel,
    val type: ScamType,
    /** The scam classifier's probability, or null when it abstained (under ~25 words). */
    val pScam: Float?,
    /** Cue and context ids that fired, for "why it fired". */
    val cues: List<String>,
    val sources: Set<RiskSource>,
    /** How likely the voice is AI-made, 0..1; null for text, or when there was too little speech. */
    val voiceClone: Float?,
    /** What the phone heard (a recording) or the text as given. Shown to the user only; never sent. */
    val transcript: String,
    /** Length of the recording in seconds; 0 for text. */
    val seconds: Float = 0f,
)

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

    /** Place a call: if no family member answers the scam alarm in 60 s, the phone calls one of them. */
    CALL_PHONE,
    NOTIFICATIONS,

    /** Do Not Disturb access: a family member's scam alarm rings even on silent or Do Not Disturb. */
    DO_NOT_DISTURB,
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

    /** The member said it was a false alarm ("Not a scam" / "I know this caller"). */
    data class FamilyAlarmCleared(val memberId: String, val label: String, val reason: FalseAlarmReason, val at: Long) : AppEvent
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
    /** The user said it's not a scam: show "Cleared" briefly, then nothing more for this call. */
    val cleared: Boolean = false,
    /** The prompter's "what we're doing": the server's stronger check is on, payments are paused (the pay guard). */
    val serverCheck: Boolean = false,
    val paymentsPaused: Boolean = false,
)

/**
 * The full-screen alarm on a family member's phone: "Mummy may be on a scam call".
 * [cleared] set: Mummy said it was a false alarm, so the screen says so and offers only OK.
 */
data class FamilyAlarmUi(val memberId: String, val label: String, val type: ScamType, val at: Long, val cleared: FalseAlarmReason? = null)

/** The red screen over a payment app while [scam] is on. */
data class PayGuardUi(val scam: Scam, val appName: String?)
