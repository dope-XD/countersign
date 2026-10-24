package app.countersign.bank

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.camera2.CameraManager
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.ContactsContract
import app.countersign.bank.data.Member
import app.countersign.bank.data.Outcome
import app.countersign.bank.data.Repo
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/**
 * What the phone itself sees about the call (CONTRACT.md, "Context signal ids"), for [CallRisk]. The raw number is only looked at here, on the phone.
 *
 * - `unknown_number`: the caller isn't family (or a contact, if the app may read contacts); else `known_contact`.
 * - `international_number`: an incoming number from outside India.
 * - `video_call_unknown`: an internet call with the camera on (the app can't see who it is).
 * - `remote_app_opened` / `payment_app_opened`: such an app came to the front during the call.
 * - `long_call`: over 15 minutes.
 * - `caller_check_failed` / `caller_verified`: the caller check said ✗ / ✓.
 *
 * Signals stay on for the rest of the call once seen (opening AnyDesk and closing it again still
 * counts), except the caller check's, where the latest answer wins.
 */
object CallContext {
    private const val LONG_CALL_MS = 15 * 60_000L

    /** AnyDesk, TeamViewer (both), QuickSupport, RustDesk. */
    private val REMOTE_APPS = setOf(
        "com.anydesk.anydeskandroid",
        "com.teamviewer.teamviewer.market.mobile",
        "com.teamviewer.quicksupport.market",
        "com.teamviewer.host.market",
        "com.carriez.flutter_hbb",
    )

    /** docs/agents/platform.md, "Payment apps". */
    val PAYMENT_APPS = setOf(
        "com.google.android.apps.nbu.paisa.user",
        "com.phonepe.app",
        "net.one97.paytm",
        "in.org.npci.upiapp",
        "com.dreamplug.androidapp",
        "in.amazon.mShop.android.shopping",
        "com.sbi.lotusintouch",
        "com.csam.icici.bank.imobile",
        "com.snapwork.hdfc",
        "com.axis.mobile",
    )

    // lazy: international() runs in plain JVM tests, where there is no main thread
    private val scope by lazy { CoroutineScope(SupervisorJob() + Dispatchers.Main) }
    private val main by lazy { Handler(Looper.getMainLooper()) }
    private val jobs = mutableListOf<Job>()
    private var callJobs = mutableListOf<Job>()
    private var camera: CameraManager? = null
    private var cameraWatch: CameraManager.AvailabilityCallback? = null

    private var callId: String? = null
    private var internet = false
    private var signals = setOf<String>()

    fun start(c: Context) {
        if (jobs.isNotEmpty()) return
        val repo = Repo.instance
        camera = c.getSystemService(CameraManager::class.java)
        jobs += scope.launch {
            repo.call.map { it?.check?.outcome }.distinctUntilChanged().collect { outcome ->
                // the latest answer wins: a ✗ and then "Yes, it's me" on the ring is verified
                val (on, off) = when (outcome) {
                    Outcome.DANGER -> "caller_check_failed" to "caller_verified"
                    Outcome.SAFE -> "caller_verified" to "caller_check_failed"
                    else -> return@collect
                }
                if (callId != null) publish(signals - off + on)
            }
        }
        jobs += scope.launch {
            ListenService.foreground.collect { pkg ->
                when (pkg) {
                    in REMOTE_APPS -> add("remote_app_opened")
                    in PAYMENT_APPS -> add("payment_app_opened")
                }
            }
        }
    }

    fun stop() {
        jobs.forEach { it.cancel() }
        jobs.clear()
        ended()
    }

    /** From [CallWatchService] when a call starts. [number] is the raw number if the app could see it. */
    fun started(c: Context, id: String, kind: String, incoming: Boolean, number: String?, caller: Member?) {
        ended()
        callId = id
        internet = kind == "internet"
        val now = mutableSetOf<String>()
        when {
            internet -> {} // no number for internet calls: only the camera says something (below)
            caller != null || inContacts(c, number) -> now += "known_contact"
            incoming -> now += "unknown_number"
        }
        if (incoming && international(number)) now += "international_number"
        signals = emptySet()
        publish(now)
        callJobs += scope.launch {
            delay(LONG_CALL_MS)
            add("long_call")
        }
        if (internet) watchCamera()
    }

    fun ended() {
        callJobs.forEach { it.cancel() }
        callJobs.clear()
        cameraWatch?.let { camera?.unregisterAvailabilityCallback(it) }
        cameraWatch = null
        callId = null
        signals = emptySet()
    }

    /** +91 / 0091 / a plain 10-digit number is India; any other "+" or "00" prefix isn't. */
    fun international(number: String?): Boolean {
        val n = number?.filter { it.isDigit() || it == '+' } ?: return false
        return when {
            n.startsWith("+") -> !n.startsWith("+91")
            n.startsWith("00") -> !n.startsWith("0091")
            else -> false
        }
    }

    private fun inContacts(c: Context, number: String?): Boolean {
        if (number.isNullOrBlank() || c.checkSelfPermission(Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) return false
        val uri = Uri.withAppendedPath(ContactsContract.PhoneLookup.CONTENT_FILTER_URI, Uri.encode(number))
        return runCatching {
            c.contentResolver.query(uri, arrayOf(ContactsContract.PhoneLookup._ID), null, null, null)?.use { it.count > 0 } ?: false
        }.getOrDefault(false)
    }

    /** A camera that becomes unavailable during an internet call is that call's video. */
    private fun watchCamera() {
        val cm = camera ?: return
        cameraWatch = object : CameraManager.AvailabilityCallback() {
            override fun onCameraUnavailable(cameraId: String) = add("video_call_unknown")
        }.also { cm.registerAvailabilityCallback(it, main) }
    }

    private fun add(signal: String?) {
        if (signal == null || callId == null || signal in signals) return
        publish(signals + signal)
    }

    private fun publish(now: Set<String>) {
        if (now == signals) return
        signals = now
        CallRisk.update { context(now) }
    }
}
