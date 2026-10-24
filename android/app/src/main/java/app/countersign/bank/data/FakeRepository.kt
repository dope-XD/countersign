package app.countersign.bank.data

import androidx.activity.ComponentActivity
import androidx.fragment.app.FragmentActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Scripted states, so every screen can be built and shown without a server or a real call. */
enum class Scenario {
    IDLE,
    CALL_CHECKING,
    CALL_VERIFIED,
    CALL_LIKELY,
    CALL_NOT_THEM_SPOOFED,
    CALL_NOT_WITH_YOU,
    CALL_CANT_REACH,
    CALL_UNKNOWN_NUMBER,
    RING_PENDING,
    RING_SAID_YES,
    RING_SAID_NO,
    PAY_GUARD,
    I_AM_BEING_RUNG,
    JOIN_REQUEST,
    NEW_USER,
    LISTEN_NEED_SPEAKER,
    LISTEN_LISTENING,
    LISTEN_WARN_DIGITAL_ARREST,
    LISTEN_SCAM,
    LISTEN_SCAM_AND_NOT_THEM,
    FAMILY_ALARM,
    MODEL_DOWNLOADING,

    /** A warn on a genuine bank call: the user presses "I know this caller". */
    LISTEN_FALSE_ALARM,

    /** The family alarm after Mummy said it was a false alarm. */
    FAMILY_ALARM_CLEARED,

    /** The caller's voice sounds AI-made: a warn with no scam words yet. */
    VOICE_CLONE_WARN,

    /** Check a recording: [lastAnalysis] is a digital-arrest scam. */
    CHECK_RECORDING_SCAM,

    /** Check a recording: [lastAnalysis] is a harmless delivery call. */
    CHECK_RECORDING_SAFE,
}

/**
 * Agent B builds against this. Actions behave plausibly: a check answers ✗ after 1.5 s,
 * a ring is answered "Yes" after 3 s, permissions are granted at once.
 * In debug builds, a long press on the home shield calls [next].
 */
class FakeRepository(start: Scenario = Scenario.IDLE) : Repository {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val now get() = System.currentTimeMillis()

    private val me = Me("c_mom", "Sunita Sharma", "+919876543210", Lang.EN, CheckChannel.RING, true)
    private val rahul = Member("c_rahul", "Rahul", "Rahul Sharma", "+919812345678", now - 86_400_000L * 40, online = true, newLink = false)
    private val priya = Member("c_priya", "Priya", "Priya Verma", "+919811111111", now - 86_400_000L * 3, online = false, newLink = false)
    private val papa = Member("c_papa", "Papa", "Ramesh Sharma", "+919822222222", now - 3_600_000L, online = true, newLink = true)
    private val family = listOf(rahul, priya, papa)

    private val _signedIn = MutableStateFlow(true)
    private val _home = MutableStateFlow<Home?>(null)
    private val _call = MutableStateFlow<LiveCall?>(null)
    private val _permissions = MutableStateFlow(Permissions(Permission.entries.toSet()))
    private val _events = MutableSharedFlow<AppEvent>(extraBufferCapacity = 16)
    private val _model = MutableStateFlow(ModelState(ModelStatus.READY, 1f, 30))

    override val signedIn: StateFlow<Boolean> = _signedIn
    override val home: StateFlow<Home?> = _home
    override val call: StateFlow<LiveCall?> = _call
    override val permissions: StateFlow<Permissions> = _permissions
    override val events: SharedFlow<AppEvent> = _events
    override val modelState: StateFlow<ModelState> = _model

    /** The family alarm currently showing on this phone (FAMILY_ALARM), for the alarm screen. */
    val alarm = MutableStateFlow<FamilyAlarmUi?>(null)

    /** The result the next checkRecording / checkText returns in the CHECK_RECORDING_* scenarios, for previews. */
    var lastAnalysis: Analysis? = null
        private set

    var scenario: Scenario = start
        private set

    init {
        play(start)
    }

    fun next() = play(Scenario.entries[(scenario.ordinal + 1) % Scenario.entries.size])

    fun play(s: Scenario) {
        scenario = s
        _signedIn.value = s != Scenario.NEW_USER
        _permissions.value = if (s == Scenario.NEW_USER) Permissions(emptySet()) else Permissions(Permission.entries.toSet())
        _home.value = if (s == Scenario.NEW_USER) null else baseHome()
        _call.value = null
        alarm.value = null
        lastAnalysis = null
        _model.value = ModelState(ModelStatus.READY, 1f, PACK_MB)
        val call = "call-1"
        fun unknown(listen: ListenState, risk: Risk? = null, speaker: Boolean = true) =
            LiveCall(call, true, true, null, null, listen = listen, onSpeaker = speaker, risk = risk)
        when (s) {
            Scenario.IDLE, Scenario.NEW_USER -> {}
            Scenario.CALL_CHECKING -> _call.value = LiveCall(call, true, false, rahul, check(rahul, Verdict.CHECKING))
            Scenario.CALL_VERIFIED -> _call.value = LiveCall(call, true, false, rahul, check(rahul, Verdict.VERIFIED))
            Scenario.CALL_LIKELY -> _call.value = LiveCall(call, true, true, rahul, check(rahul, Verdict.LIKELY))
            Scenario.CALL_NOT_THEM_SPOOFED -> _call.value = LiveCall(call, true, false, rahul, check(rahul, Verdict.NOT_THEM, spoof = true))
            Scenario.CALL_NOT_WITH_YOU -> _call.value = LiveCall(call, true, true, rahul, check(rahul, Verdict.NOT_WITH_YOU))
            Scenario.CALL_CANT_REACH -> _call.value = LiveCall(call, true, true, priya, check(priya, Verdict.CANT_REACH))
            Scenario.CALL_UNKNOWN_NUMBER -> _call.value = LiveCall(call, true, true, null, null)
            Scenario.RING_PENDING -> _call.value = LiveCall(call, true, true, null, check(rahul, Verdict.NOT_THEM, ring = RingState.RINGING))
            Scenario.RING_SAID_YES -> _call.value = LiveCall(call, true, true, null, check(rahul, Verdict.NOT_THEM, ring = RingState.YES))
            Scenario.RING_SAID_NO -> {
                val c = check(rahul, Verdict.NOT_THEM, ring = RingState.NO)
                _call.value = LiveCall(call, true, true, null, c)
                setScam(c)
            }
            Scenario.PAY_GUARD -> {
                val c = check(rahul, Verdict.NOT_THEM, spoof = true)
                _call.value = LiveCall(call, true, true, rahul, c)
                setScam(c)
            }
            Scenario.I_AM_BEING_RUNG -> _home.update { h ->
                h?.copy(
                    approvals = listOf(
                        Approval(
                            "apv_1", ApprovalKind.CALL_CHECK, "Papa", "Is it you on Papa's call?",
                            "Someone on a call to Papa says they're you.", "ch", CheckChannel.RING, now + 120_000, "pending",
                        ),
                    ),
                )
            }
            Scenario.JOIN_REQUEST -> _home.update { h -> h?.copy(joinRequests = listOf(JoinRequest("c_neha", "Neha Gupta", "Mummy"))) }
            Scenario.LISTEN_NEED_SPEAKER -> _call.value = unknown(ListenState.NEED_SPEAKER, speaker = false)
            Scenario.LISTEN_LISTENING -> _call.value = unknown(ListenState.LISTENING, risk(RiskLevel.WATCH, ScamType.UNKNOWN, "authority"))
            Scenario.LISTEN_WARN_DIGITAL_ARREST ->
                _call.value = unknown(ListenState.LISTENING, risk(RiskLevel.WARN, ScamType.DIGITAL_ARREST, "authority", "threat"))
            Scenario.LISTEN_SCAM -> {
                val r = risk(RiskLevel.SCAM, ScamType.DIGITAL_ARREST, "authority", "threat", "secrecy", "money_ask", sources = setOf(RiskSource.CUES, RiskSource.PHONE_AI))
                _call.value = unknown(ListenState.LISTENING, r)
                _home.update { h -> h?.copy(scam = Scam("chk_l", "", "", "listener:digital_arrest", now + 600_000)) }
            }
            Scenario.LISTEN_SCAM_AND_NOT_THEM -> {
                val c = check(rahul, Verdict.NOT_THEM, spoof = true)
                val r = risk(RiskLevel.SCAM, ScamType.FAMILY_EMERGENCY, "family_emergency", "money_ask", "urgency", sources = setOf(RiskSource.CUES, RiskSource.CALLER_CHECK))
                _call.value = LiveCall(call, true, true, rahul, c, ListenState.LISTENING, true, r)
                setScam(c)
            }
            Scenario.FAMILY_ALARM -> {
                val a = FamilyAlarmUi(papa.id, papa.label, ScamType.DIGITAL_ARREST, now)
                alarm.value = a
                _events.tryEmit(AppEvent.FamilyAlarm(a.memberId, a.label, a.type, a.at))
            }
            Scenario.MODEL_DOWNLOADING -> {
                _model.value = ModelState(ModelStatus.DOWNLOADING, 0.35f, PACK_MB)
                _call.value = unknown(ListenState.NO_MODEL)
            }
            Scenario.LISTEN_FALSE_ALARM ->
                _call.value = unknown(ListenState.LISTENING, risk(RiskLevel.WARN, ScamType.BANK_KYC, "authority", "verification_pretext", "urgency"))
            Scenario.FAMILY_ALARM_CLEARED -> {
                val a = FamilyAlarmUi(papa.id, papa.label, ScamType.DIGITAL_ARREST, now - 40_000, cleared = FalseAlarmReason.KNOW_CALLER)
                alarm.value = a
                _events.tryEmit(AppEvent.FamilyAlarmCleared(a.memberId, a.label, FalseAlarmReason.KNOW_CALLER, now))
            }
            Scenario.VOICE_CLONE_WARN ->
                _call.value = unknown(
                    ListenState.LISTENING,
                    risk(RiskLevel.WARN, ScamType.UNKNOWN, "synthetic_voice", sources = setOf(RiskSource.VOICE)),
                )
            Scenario.CHECK_RECORDING_SCAM -> lastAnalysis = SCAM_ANALYSIS
            Scenario.CHECK_RECORDING_SAFE -> lastAnalysis = SAFE_ANALYSIS
        }
    }

    private fun baseHome() = Home(
        me = me,
        family = family,
        joinRequests = emptyList(),
        approvals = emptyList(),
        checks = listOf(
            check(rahul, Verdict.VERIFIED, ago = 3_600_000),
            check(priya, Verdict.NOT_THEM, ring = RingState.NO, ago = 86_400_000),
            check(papa, Verdict.CANT_REACH, ring = RingState.YES, ago = 2 * 86_400_000L),
        ),
        scam = null,
    )

    private var seq = 0

    private fun check(m: Member, v: Verdict, spoof: Boolean = false, ring: RingState = RingState.NONE, ago: Long = 0) = Check(
        id = "chk_${++seq}", callId = "call-1", memberId = m.id, label = m.label, verdict = v,
        numberMatched = spoof || v == Verdict.VERIFIED, spoofSuspected = spoof, ring = ring,
        createdAt = now - ago, decidedAt = if (v == Verdict.CHECKING) null else now - ago + 2_000,
    )

    private fun risk(level: RiskLevel, type: ScamType, vararg cues: String, sources: Set<RiskSource> = setOf(RiskSource.CUES)) =
        Risk(level, type, cues.toList(), sources, now)

    private fun setScam(c: Check) =
        _home.update { h -> h?.copy(scam = Scam(c.id, c.memberId, c.label, if (c.ring == RingState.NO) "ring_no" else c.verdict.wire, now + 600_000)) }

    private fun member(id: String) = family.firstOrNull { it.id == id } ?: error("Not in your family.")

    // ---- Repository
    override suspend fun signUp(name: String, mobile: String, lang: Lang): Me {
        delay(600)
        if (mobile.filter(Char::isDigit).length < 10) error("Enter a 10-digit mobile number.")
        _signedIn.value = true
        _home.value = baseHome().copy(me = me.copy(name = name, lang = lang), family = emptyList(), checks = emptyList())
        return _home.value!!.me
    }

    override suspend fun refresh() = delay(300)

    override suspend fun setPrefs(lang: Lang?, channel: CheckChannel?, shareCallStatus: Boolean?): Me {
        val h = _home.value ?: error("Not signed in.")
        val m = h.me.copy(lang = lang ?: h.me.lang, channel = channel ?: h.me.channel, shareCallStatus = shareCallStatus ?: h.me.shareCallStatus)
        _home.value = h.copy(me = m)
        return m
    }

    override fun signOut() = play(Scenario.NEW_USER)

    override suspend fun invite(): Invite {
        delay(300)
        return Invite("482913", now + 600_000, "csbank://family?code=482913")
    }

    override suspend fun join(code: String, label: String) {
        delay(500)
        if (code.length != 6) error("That code has expired or doesn't exist. Ask for a new one.")
        scope.launch {
            delay(3_000)
            val m = Member("c_new", label, "Neha Gupta", "+919833333333", now, online = true, newLink = true)
            _home.update { h -> h?.copy(family = h.family + m) }
            _events.emit(AppEvent.FamilyJoined(m.id, m.name))
        }
    }

    override suspend fun confirmJoin(customerId: String, label: String) {
        delay(300)
        _home.update { h ->
            val r = h?.joinRequests?.firstOrNull { it.customerId == customerId } ?: return@update h
            h.copy(joinRequests = h.joinRequests - r, family = h.family + Member(customerId, label, r.name, "+919833333333", now, online = true, newLink = true))
        }
    }

    override suspend fun declineJoin(customerId: String) =
        _home.update { h -> h?.copy(joinRequests = h.joinRequests.filterNot { it.customerId == customerId }) }

    override suspend fun removeMember(memberId: String) = _home.update { h -> h?.copy(family = h.family.filterNot { it.id == memberId }) }

    override suspend fun check(memberId: String): Check {
        val m = member(memberId)
        val pending = check(m, Verdict.CHECKING)
        _call.update { it?.copy(check = pending) }
        scope.launch {
            delay(1_500)
            val done = pending.copy(verdict = Verdict.NOT_THEM, decidedAt = now)
            _call.update { it?.copy(check = done) }
            setScam(done)
        }
        return pending
    }

    override suspend fun ring(checkId: String): Check {
        val c = _call.value?.check?.takeIf { it.id == checkId } ?: error("That check has ended.")
        val ringing = c.copy(ring = RingState.RINGING)
        _call.update { it?.copy(check = ringing) }
        scope.launch {
            delay(3_000)
            _call.update { it?.copy(check = ringing.copy(ring = RingState.YES)) }
        }
        return ringing
    }

    override fun callMember(memberId: String) {}

    override suspend fun dismissScam() = _home.update { it?.copy(scam = null) }

    override suspend fun answer(approvalId: String, yes: Boolean, activity: FragmentActivity): Approval {
        delay(400)
        val a = _home.value?.approvals?.firstOrNull { it.id == approvalId } ?: error("This check has ended.")
        _home.update { h -> h?.copy(approvals = h.approvals.filterNot { it.id == approvalId }) }
        return a.copy(status = if (yes) "approved" else "declined")
    }

    override fun request(permission: Permission, activity: ComponentActivity) =
        _permissions.update { Permissions(it.granted + permission) }

    override suspend fun downloadModels() {
        for (i in 1..10) {
            _model.value = ModelState(ModelStatus.DOWNLOADING, i / 10f, 30)
            delay(200)
        }
        _model.value = ModelState(ModelStatus.READY, 1f, 30)
    }

    override suspend fun setListening(listenCalls: Boolean?, smsFallback: Boolean?): Me {
        val h = _home.value ?: error("Not signed in.")
        val m = h.me.copy(
            listenCalls = listenCalls ?: h.me.listenCalls,
            smsFallback = smsFallback ?: h.me.smsFallback,
        )
        _home.value = h.copy(me = m)
        return m
    }

    override suspend fun alertFamily() {
        delay(300)
        _call.update { c ->
            c?.copy(risk = Risk(RiskLevel.SCAM, c.risk?.type ?: ScamType.UNKNOWN, c.risk?.cues.orEmpty(), (c.risk?.sources.orEmpty()) + RiskSource.USER, now))
        }
    }

    override fun messageMember(memberId: String) {}

    override suspend fun notAScam(reason: FalseAlarmReason) {
        delay(300)
        _call.update { it?.copy(risk = null, cleared = true) }
        _home.update { it?.copy(scam = null) }
    }

    override suspend fun checkRecording(uri: android.net.Uri): Analysis {
        delay(2_500)
        return lastAnalysis ?: SCAM_ANALYSIS
    }

    override suspend fun checkText(text: String): Analysis {
        delay(600)
        lastAnalysis?.let { return it }
        // a stand-in for the real analyzer: a few loud words make a scam, anything else is safe
        val loud = listOf("police", "arrest", "otp", "kyc", "anydesk", "पुलिस", "गिरफ्तार").filter { it in text.lowercase() }
        return if (loud.size >= 2) SCAM_ANALYSIS.copy(transcript = text, voiceClone = null, seconds = 0f) else SAFE_ANALYSIS.copy(transcript = text, voiceClone = null, seconds = 0f)
    }

    companion object {
        const val PACK_MB = 180

        val SCAM_ANALYSIS = Analysis(
            level = RiskLevel.SCAM,
            type = ScamType.DIGITAL_ARREST,
            pScam = 0.94f,
            cues = listOf("authority", "threat", "secrecy", "money_ask"),
            sources = setOf(RiskSource.CUES, RiskSource.PHONE_AI),
            voiceClone = 0.12f,
            transcript = "This is inspector Sharma from Mumbai police. Your Aadhaar is linked to a money laundering case. " +
                "Do not tell anyone. Transfer the money to the safe account now or you will be arrested.",
            seconds = 41f,
        )

        val SAFE_ANALYSIS = Analysis(
            level = RiskLevel.NONE,
            type = ScamType.UNKNOWN,
            pScam = 0.04f,
            cues = emptyList(),
            sources = emptySet(),
            voiceClone = 0.08f,
            transcript = "Hello madam, I'm outside your building with the parcel from Amazon. Should I leave it with the guard?",
            seconds = 12f,
        )
    }
}
