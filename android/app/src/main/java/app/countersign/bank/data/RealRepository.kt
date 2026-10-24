package app.countersign.bank.data

import android.Manifest
import android.app.Activity
import android.app.AppOpsManager
import android.app.Application
import android.app.NotificationManager
import android.app.role.RoleManager
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.fragment.app.FragmentActivity
import app.countersign.bank.Api
import app.countersign.bank.ApiError
import app.countersign.bank.Bus
import app.countersign.bank.CallWatchService
import app.countersign.bank.DeviceKey
import app.countersign.bank.Notify
import app.countersign.bank.Prefs
import app.countersign.bank.Ringer
import app.countersign.bank.dbl
import app.countersign.bank.obj
import app.countersign.bank.objects
import app.countersign.bank.str
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.UUID

/**
 * The app on the real engine (docs/agents/CONTRACT.md): the `/api/m` calls through [Api], and the
 * `/ws/events` socket that keeps [home] and [call] fresh. [CallWatchService] keeps the process
 * alive and opens the socket with [connect] while the phone is signed in.
 */
class RealRepository(private val app: Application) : Repository {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val main = Handler(Looper.getMainLooper())

    private val _signedIn = MutableStateFlow(Prefs.signedIn)
    private val _home = MutableStateFlow<Home?>(null)
    private val _call = MutableStateFlow<LiveCall?>(null)
    private val _permissions = MutableStateFlow(Permissions(emptySet()))
    private val _events = MutableSharedFlow<AppEvent>(extraBufferCapacity = 16)

    override val signedIn: StateFlow<Boolean> = _signedIn
    override val home: StateFlow<Home?> = _home
    override val call: StateFlow<LiveCall?> = _call
    override val permissions: StateFlow<Permissions> = _permissions
    override val events: SharedFlow<AppEvent> = _events

    init {
        checkPermissions()
        // the user comes back from a system prompt or settings page: see what they granted
        app.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
            override fun onActivityResumed(activity: Activity) = checkPermissions()
            override fun onActivityCreated(activity: Activity, savedInstanceState: Bundle?) {}
            override fun onActivityStarted(activity: Activity) {}
            override fun onActivityPaused(activity: Activity) {}
            override fun onActivityStopped(activity: Activity) {}
            override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) {}
            override fun onActivityDestroyed(activity: Activity) {}
        })
        if (Prefs.signedIn) scope.launch { runCatching { refresh() } }
    }

    // ------------------------------------------------------------------ account
    override suspend fun signUp(name: String, mobile: String, lang: Lang): Me {
        if (!DeviceKey.screenLockSet(app)) {
            throw ApiError("Set a screen lock (PIN, pattern or fingerprint) on this phone first. Your answers are protected by it.", 0)
        }
        val key = try {
            DeviceKey.create()
        } catch (e: Exception) {
            throw ApiError("This phone couldn't make its key: ${e.message}", 0)
        }
        val r = Api.post(
            "/api/m/signup",
            JSONObject().put("name", name).put("mobile", mobile).put("lang", lang.code)
                .put("check_channel", CheckChannel.RING.wire).put("share_call_status", true)
                .put("public_key", key).put("device", "${Build.MANUFACTURER} ${Build.MODEL}"),
        )
        val me = parseMe(r.obj("me") ?: r.getJSONObject("account"))
        Prefs.token = r.getString("token")
        Prefs.customerId = me.id
        _signedIn.value = true
        _home.value = Home(me, emptyList(), emptyList(), emptyList(), emptyList(), null)
        // from the background (a test, or the app closed mid sign-up) Android refuses; MainActivity starts it again
        runCatching { CallWatchService.start(app) }.onFailure { Log.w(TAG, "watch not started: $it") }
        runCatching { refresh() }
        return me
    }

    override suspend fun refresh() {
        if (!Prefs.signedIn) return
        _home.value = parseHome(Api.get("/api/m/home"))
    }

    override suspend fun setPrefs(lang: Lang?, channel: CheckChannel?, shareCallStatus: Boolean?): Me {
        val body = JSONObject()
        lang?.let { body.put("lang", it.code) }
        channel?.let { body.put("check_channel", it.wire) }
        shareCallStatus?.let { body.put("share_call_status", it) }
        val r = Api.post("/api/m/prefs", body)
        val me = parseMe(r.obj("me") ?: r.obj("account") ?: r)
        _home.update { it?.copy(me = me) }
        return me
    }

    override fun signOut() {
        disconnect()
        CallWatchService.stop(app)
        DeviceKey.delete()
        Prefs.signOut()
        _signedIn.value = false
        _home.value = null
        _call.value = null
    }

    // ------------------------------------------------------------------ family
    override suspend fun invite(): Invite {
        val r = Api.post("/api/m/family/invite")
        return Invite(r.getString("code"), System.currentTimeMillis() + r.optLong("expires_in", 600) * 1000, r.getString("qr"))
    }

    override suspend fun join(code: String, label: String) {
        Api.post("/api/m/family/join", JSONObject().put("code", code).put("label", label))
    }

    override suspend fun confirmJoin(customerId: String, label: String) {
        val r = Api.post("/api/m/family/confirm", JSONObject().put("customer_id", customerId).put("label", label))
        val family = r.getJSONArray("family").objects().map(::parseMember)
        _home.update { h -> h?.copy(family = family, joinRequests = h.joinRequests.filterNot { it.customerId == customerId }) }
    }

    override suspend fun declineJoin(customerId: String) {
        Api.post("/api/m/family/decline/$customerId")
        _home.update { h -> h?.copy(joinRequests = h.joinRequests.filterNot { it.customerId == customerId }) }
    }

    override suspend fun removeMember(memberId: String) {
        val r = Api.delete("/api/m/family/$memberId")
        val family = r.getJSONArray("family").objects().map(::parseMember)
        _home.update { it?.copy(family = family) }
    }

    // ------------------------------------------------------------------ calls
    override suspend fun check(memberId: String): Check {
        val callId = _call.value?.id ?: UUID.randomUUID().toString()
        val r = Api.post("/api/m/checks", JSONObject().put("call_id", callId).put("claimed", memberId).put("number_matched", false).put("via", "manual"))
        return parseCheck(r).also(::takeCheck)
    }

    override suspend fun ring(checkId: String): Check = parseCheck(Api.post("/api/m/checks/$checkId/ring")).also(::takeCheck)

    override fun callMember(memberId: String) {
        val m = _home.value?.family?.firstOrNull { it.id == memberId } ?: return
        app.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${m.mobile}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    override suspend fun dismissScam() {
        Api.post("/api/m/scam/dismiss")
        _home.update { it?.copy(scam = null) }
    }

    /** The phone's own call, from [CallWatchService]: null when it ends. */
    fun setCall(c: LiveCall?) {
        _call.value = c?.copy(check = c.check ?: _call.value?.takeIf { it.id == c.id }?.check)
    }

    private fun takeCheck(c: Check) {
        _call.update { lc -> if (lc != null && (lc.id == c.callId || lc.check?.id == c.id)) lc.copy(check = c) else lc }
        _home.update { h -> h?.copy(checks = (listOf(c) + h.checks.filterNot { it.id == c.id }).sortedByDescending { it.createdAt }.take(10)) }
    }

    // ------------------------------------------------------------------ answering a ring
    override suspend fun answer(approvalId: String, yes: Boolean, activity: FragmentActivity): Approval {
        val a = _home.value?.approvals?.firstOrNull { it.id == approvalId } ?: throw ApiError("This check has ended.", 0)
        val body = JSONObject().put("decision", if (yes) "approve" else "decline")
        if (yes) {
            val signature = try {
                DeviceKey.sign(activity, "approve:${a.id}:${a.challenge}", "Confirm it's you", a.question)
            } catch (e: DeviceKey.Cancelled) {
                throw ApiError("Not confirmed: ${e.message}", 0)
            }
            body.put("signature", signature)
        }
        val r = Api.post("/api/m/approvals/$approvalId/decide", body)
        Ringer.stop()
        Notify.cancel(app, approvalId)
        _home.update { h -> h?.copy(approvals = h.approvals.filterNot { it.id == approvalId }) }
        return runCatching { parseApproval(r) }.getOrElse { a.copy(status = if (yes) "approved" else "declined") }
    }

    // ------------------------------------------------------------------ permissions
    private fun has(p: String) = app.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED

    private fun role(name: String) = app.getSystemService(RoleManager::class.java).let { it.isRoleAvailable(name) && it.isRoleHeld(name) }

    @Suppress("DEPRECATION") // unsafeCheckOpNoThrow is still the way to read the usage-access grant
    fun checkPermissions() {
        val ops = app.getSystemService(AppOpsManager::class.java)
        val granted = buildSet {
            if (has(Manifest.permission.READ_PHONE_STATE)) add(Permission.PHONE)
            if (role(RoleManager.ROLE_CALL_SCREENING)) add(Permission.CALL_SCREENING)
            if (role(RoleManager.ROLE_CALL_REDIRECTION)) add(Permission.CALL_REDIRECTION)
            if (app.getSystemService(NotificationManager::class.java).areNotificationsEnabled()) add(Permission.NOTIFICATIONS)
            if (Settings.canDrawOverlays(app)) add(Permission.OVERLAY)
            if (ops.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, android.os.Process.myUid(), app.packageName) == AppOpsManager.MODE_ALLOWED) {
                add(Permission.USAGE_ACCESS)
            }
            if (Notify.canRing(app)) add(Permission.FULL_SCREEN)
            if (app.getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(app.packageName)) add(Permission.BATTERY)
        }
        _permissions.value = Permissions(granted)
    }

    @Suppress("DEPRECATION") // startActivityForResult: the result is read on resume, not from the callback
    override fun request(permission: Permission, activity: ComponentActivity) {
        val pkg = Uri.parse("package:${app.packageName}")
        fun open(action: String, data: Uri? = pkg) = runCatching { activity.startActivity(Intent(action, data)) }
            .recoverCatching { activity.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, pkg)) }

        fun ask(p: String) {
            // asked before and the user ticked "don't ask again": only the settings page can change it now
            if (Prefs.asked(p) && !activity.shouldShowRequestPermissionRationale(p)) {
                open(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
            } else {
                Prefs.markAsked(p)
                activity.requestPermissions(arrayOf(p), permission.ordinal)
            }
        }

        fun askRole(name: String) {
            val rm = app.getSystemService(RoleManager::class.java)
            if (rm.isRoleAvailable(name) && !rm.isRoleHeld(name)) activity.startActivityForResult(rm.createRequestRoleIntent(name), permission.ordinal)
        }
        when (permission) {
            Permission.PHONE -> ask(Manifest.permission.READ_PHONE_STATE)
            Permission.CALL_SCREENING -> askRole(RoleManager.ROLE_CALL_SCREENING)
            Permission.CALL_REDIRECTION -> askRole(RoleManager.ROLE_CALL_REDIRECTION)
            Permission.NOTIFICATIONS ->
                if (Build.VERSION.SDK_INT >= 33 && !has(Manifest.permission.POST_NOTIFICATIONS)) {
                    ask(Manifest.permission.POST_NOTIFICATIONS)
                } else {
                    runCatching { activity.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, app.packageName)) }
                }
            Permission.OVERLAY -> open(Settings.ACTION_MANAGE_OVERLAY_PERMISSION)
            Permission.USAGE_ACCESS -> open(Settings.ACTION_USAGE_ACCESS_SETTINGS, null)
            Permission.FULL_SCREEN -> if (Build.VERSION.SDK_INT >= 34) open(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT)
            Permission.BATTERY -> open(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
            // added by the call-listener contract change; agent C implements these
            Permission.OUTGOING_CALLS, Permission.MICROPHONE, Permission.ACCESSIBILITY, Permission.SMS -> {}
        }
    }

    // ------------------------------------------------------------------ events socket
    private var socket: WebSocket? = null
    private var retries = 0
    private var wanted = false

    private val heartbeat = object : Runnable {
        override fun run() {
            socket?.send("hb") // tells the engine the app is alive: family see the green dot
            main.postDelayed(this, 20_000)
        }
    }

    /** Opens `/ws/events` for this account and keeps it open (with backoff) until [disconnect]. */
    fun connect() {
        wanted = true
        if (socket != null) return
        val cid = Prefs.customerId ?: return
        val url = Prefs.server.replaceFirst(Regex("^http"), "ws") + "/ws/events?topics=app:$cid"
        socket = Api.http.newWebSocket(Api.request("").url(url).build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                retries = 0
                scope.launch { runCatching { refresh() } } // catch up on anything missed while it was closed
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                main.post { onEvent(text) }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.w(TAG, "events dropped: $t")
                main.post { reconnect(webSocket) }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                main.post { reconnect(webSocket) }
            }
        })
        main.removeCallbacks(heartbeat)
        main.postDelayed(heartbeat, 20_000)
    }

    fun disconnect() {
        wanted = false
        main.removeCallbacks(heartbeat)
        socket?.close(1000, "bye")
        socket = null
    }

    private fun reconnect(dead: WebSocket) {
        if (socket !== dead) return
        socket = null
        if (!wanted || !Prefs.signedIn) return
        main.postDelayed({ if (wanted) connect() }, minOf(30_000L, 1000L shl minOf(retries++, 5)))
    }

    private fun onEvent(text: String) {
        val e = try {
            JSONObject(text)
        } catch (x: Exception) {
            return
        }
        Bus.events.tryEmit(e) // the old screens still listen here until B replaces them
        try {
            when (e.optString("type")) {
                "call_check" -> takeCheck(parseCheck(e.getJSONObject("check")))
                "approval" -> {
                    val raw = e.getJSONObject("approval")
                    val a = parseApproval(raw)
                    _home.update { h ->
                        h?.copy(approvals = h.approvals.filterNot { it.id == a.id } + listOfNotNull(a.takeIf { it.status == "pending" }))
                    }
                    if (a.status == "pending") Notify.approval(app, raw)
                }
                "spoof_alert" -> _events.tryEmit(AppEvent.SpoofAlert(e.optString("label").ifEmpty { e.optString("by") }, ms(e.optDouble("at"))))
                "scam" -> _home.update { it?.copy(scam = e.obj("scam")?.let { s -> parseScam(s) }) }
                "family_request" -> {
                    _events.tryEmit(AppEvent.FamilyRequest(e.optString("customer_id"), e.optString("name")))
                    Notify.news(app, "${e.optString("name")} wants to join your family", "Open the app to confirm. Only accept people you know in person.")
                    scope.launch { runCatching { refresh() } }
                }
                "family_joined" -> {
                    _events.tryEmit(AppEvent.FamilyJoined(e.optString("customer_id"), e.optString("name")))
                    Notify.news(app, "You're now family with ${e.optString("name")}", "You can check with each other when someone calls saying they're family.")
                    scope.launch { runCatching { refresh() } }
                }
                "online" -> {
                    val id = e.optString("member")
                    val online = e.optBoolean("online")
                    _home.update { h -> h?.copy(family = h.family.map { if (it.id == id) it.copy(online = online) else it }) }
                }
            }
        } catch (x: Exception) {
            Log.w(TAG, "bad ${e.optString("type")} event: $x")
        }
    }

    // ------------------------------------------------------------------ JSON → data/Models.kt
    private fun ms(seconds: Double): Long = (seconds * 1000).toLong()

    private fun parseMe(o: JSONObject) = Me(
        id = o.getString("id"),
        name = o.getString("name"),
        mobile = o.getString("mobile"),
        lang = Lang.entries.firstOrNull { it.code == o.optString("lang") } ?: Lang.EN,
        channel = CheckChannel.entries.firstOrNull { it.wire == o.optString("check_channel") } ?: CheckChannel.RING,
        shareCallStatus = o.optBoolean("share_call_status", true),
    )

    private fun parseMember(o: JSONObject) = Member(
        id = o.getString("id"),
        label = o.getString("label"),
        name = o.getString("name"),
        mobile = o.getString("mobile"),
        since = ms(o.optDouble("since", 0.0)),
        online = o.optBoolean("online"),
        newLink = o.optBoolean("new_link"),
    )

    private fun parseJoin(o: JSONObject) = JoinRequest(o.getString("customer_id"), o.getString("name"), o.optString("label"))

    private fun parseCheck(o: JSONObject) = Check(
        id = o.getString("id"),
        callId = o.optString("call_id"),
        memberId = o.optString("member"),
        label = o.optString("label"),
        verdict = Verdict.entries.firstOrNull { it.wire == o.optString("verdict") } ?: Verdict.CANT_REACH,
        numberMatched = o.optBoolean("number_matched"),
        spoofSuspected = o.optBoolean("spoof_suspected"),
        ring = RingState.entries.firstOrNull { it.wire == o.optString("ring") } ?: RingState.NONE,
        createdAt = ms(o.optDouble("created_at", 0.0)),
        decidedAt = o.dbl("decided_at")?.let(::ms),
    )

    private fun parseScam(o: JSONObject, checks: List<Check> = _home.value?.checks.orEmpty()): Scam {
        val checkId = o.optString("check_id")
        // older engines left out the member: take it from the check the scam came from
        val member = o.str("member") ?: (checks + listOfNotNull(_call.value?.check)).firstOrNull { it.id == checkId }?.memberId.orEmpty()
        return Scam(
            checkId = checkId,
            memberId = member,
            label = o.optString("label"),
            reason = o.optString("reason", Verdict.NOT_THEM.wire),
            until = ms(o.optDouble("until", 0.0)),
        )
    }

    private fun parseApproval(o: JSONObject): Approval {
        val s = o.obj("summary") // the engine's older shape kept the words in a summary
        fun text(name: String) = o.str(name) ?: s?.str(name).orEmpty()
        return Approval(
            id = o.getString("id"),
            kind = ApprovalKind.entries.firstOrNull { it.wire == o.optString("kind") } ?: ApprovalKind.BANK_CALL,
            from = text("from"),
            question = text("question"),
            detail = text("detail"),
            challenge = o.optString("challenge"),
            channel = CheckChannel.entries.firstOrNull { it.wire == o.optString("deliver") } ?: CheckChannel.NOTIFY,
            expiresAt = ms(o.optDouble("expires_at", 0.0)),
            status = o.optString("status", "pending"),
        )
    }

    private fun parseHome(o: JSONObject): Home {
        val checks = o.optJSONArray("checks")?.objects()?.map(::parseCheck).orEmpty()
        return Home(
            // until engine #2 lands, the dev server sends the old "account" instead of "me"
            me = parseMe(o.obj("me") ?: o.getJSONObject("account")),
            family = o.getJSONArray("family").objects().map(::parseMember),
            joinRequests = o.optJSONArray("join_requests")?.objects()?.map(::parseJoin).orEmpty(),
            approvals = o.optJSONArray("approvals")?.objects()?.map(::parseApproval).orEmpty(),
            checks = checks,
            scam = o.obj("scam")?.let { parseScam(it, checks) },
        )
    }

    companion object {
        private const val TAG = "RealRepository"
    }
}
