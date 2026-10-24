package app.countersign.bank

import android.content.Context
import android.graphics.PixelFormat
import android.provider.Settings
import android.util.Log
import android.view.Gravity
import android.view.WindowManager
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import androidx.lifecycle.setViewTreeLifecycleOwner
import androidx.savedstate.SavedStateRegistry
import androidx.savedstate.SavedStateRegistryController
import androidx.savedstate.SavedStateRegistryOwner
import androidx.savedstate.setViewTreeSavedStateRegistryOwner
import app.countersign.bank.data.CallCheckUi
import app.countersign.bank.data.Home
import app.countersign.bank.data.LiveCall
import app.countersign.bank.data.Outcome
import app.countersign.bank.data.Repo
import app.countersign.bank.data.Verdict
import app.countersign.bank.ui.Language
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/**
 * The call check card over the dialer: an accessibility overlay from [ListenService] when the
 * listener is on, else a TYPE_APPLICATION_OVERLAY window (needs "Display over other apps"), at the
 * top of the screen, shown while [Repo.instance]'s call is ringing or
 * answered and removed when it ends. Not focusable, so the dialer keeps the keyboard and its
 * end-call button. CallWatchService runs it with [start] / [stop].
 */
object Overlay {
    private const val TAG = "Overlay"
    private const val BELOW_BANNER_DP = 200
    private val repo get() = Repo.instance
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var watching: Job? = null
    private var card: Window? = null

    /** What the card is shown from: the listener's accessibility service, or the app with "Display over other apps". */
    private var cardHost: Context? = null

    /** The call the user closed the card on: it stays closed until the next call. */
    private var closedCall: String? = null

    /** Android hides overlay windows while the lock screen is up, so then [CallCheckNotice] says it instead (also without the overlay permission). */
    private val locked = MutableStateFlow(false)
    private var lockWatch: Job? = null

    fun start(c: Context) {
        if (watching != null) return
        val app = c.applicationContext
        // the screen-off and unlock broadcasts can arrive many seconds late, so ask once a second during a call
        lockWatch = scope.launch {
            repo.call.map { it != null }.distinctUntilChanged().collectLatest { onCall ->
                while (onCall) {
                    locked.value = CallCheckNotice.locked(app)
                    delay(1_000)
                }
            }
        }
        watching = scope.launch {
            combine(repo.call, repo.home, locked, ListenService.host) { call, home, isLocked, listener -> Seen(call, home, isLocked, listener) }.collect { (call, home, isLocked, listener) ->
                // Android hides every overlay over the lock screen (an accessibility one too), and an app
                // overlay needs "Display over other apps": when the card can't be seen, the notification says it
                val hidden = isLocked || (listener == null && !Settings.canDrawOverlays(app))
                if (call != null && hidden && call.id != closedCall) {
                    CallCheckNotice.show(app, CallCheckUi(call.caller, call.check, home?.family.orEmpty()))
                } else {
                    CallCheckNotice.cancel(app)
                }
                val wantHost: Context = listener ?: app
                when {
                    call == null -> hide()
                    call.id == closedCall -> hide()
                    card == null -> show(wantHost)
                    cardHost !== wantHost -> { // accessibility turned on or off mid-call: move the card
                        hide()
                        show(wantHost)
                    }
                }
                // while it rings, the dialer's incoming-call banner sits on top of every overlay: go under it
                card?.moveTo(if (call != null && call.incoming && !call.answered) (BELOW_BANNER_DP * app.resources.displayMetrics.density).toInt() else 0)
            }
        }
    }

    fun stop(c: Context) {
        watching?.cancel()
        watching = null
        lockWatch?.cancel()
        lockWatch = null
        hide()
        CallCheckNotice.cancel(c)
    }

    private fun show(c: Context) {
        val accessibility = c is ListenService
        if (!accessibility && !Settings.canDrawOverlays(c)) {
            Log.w(TAG, "no overlay permission: the card can't show")
            return
        }
        // an accessibility overlay needs no permission of its own, and keeps the listener's mic priority
        val type = if (accessibility) WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY else WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        cardHost = c
        card = Window(c, Gravity.TOP, type).also { w ->
            w.show {
                val call by repo.call.collectAsState()
                val home by repo.home.collectAsState()
                val now = call ?: return@show
                CallCheckCardStub(
                    state = CallCheckUi(now.caller, now.check, home?.family.orEmpty()),
                    onRing = { now.check?.let { act("ring") { repo.ring(it.id) } } },
                    onCall = { (now.check?.memberId ?: now.caller?.id)?.let(repo::callMember) },
                    onPickMember = { id -> act("check") { repo.check(id) } },
                    onClose = {
                        closedCall = now.id
                        hide()
                    },
                )
            }
        }
    }

    /** A button on the card: the card shows the result through [Repo.instance]'s flows, so only failures matter here. */
    private fun act(what: String, block: suspend () -> Unit) {
        scope.launch {
            try {
                block()
            } catch (e: Exception) {
                Log.w(TAG, "$what failed: ${e.message}")
            }
        }
    }

    private fun hide() {
        card?.remove()
        card = null
        cardHost = null
    }

    private data class Seen(val call: LiveCall?, val home: Home?, val locked: Boolean, val listener: ListenService?)

    /** A Compose window outside any Activity: it brings its own lifecycle and saved state. */
    private class Window(private val c: Context, private val edge: Int, private val type: Int) : LifecycleOwner, SavedStateRegistryOwner {
        private val lifecycleRegistry = LifecycleRegistry(this)
        private val savedState = SavedStateRegistryController.create(this)
        private val wm = c.getSystemService(WindowManager::class.java)
        private var view: ComposeView? = null

        override val lifecycle: Lifecycle get() = lifecycleRegistry
        override val savedStateRegistry: SavedStateRegistry get() = savedState.savedStateRegistry

        fun show(content: @Composable () -> Unit) {
            savedState.performRestore(null)
            lifecycleRegistry.currentState = Lifecycle.State.RESUMED
            val v = ComposeView(Language.wrap(c)).apply { // the window comes from c; the words in the app's language
                setViewTreeLifecycleOwner(this@Window)
                setViewTreeSavedStateRegistryOwner(this@Window)
                setContent(content)
            }
            val lp = WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.WRAP_CONTENT,
                type,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                PixelFormat.TRANSLUCENT,
            ).apply { gravity = edge }
            try {
                wm.addView(v, lp)
                view = v
            } catch (e: Exception) { // permission withdrawn between the check and here
                Log.w(TAG, "card not shown: $e")
                lifecycleRegistry.currentState = Lifecycle.State.DESTROYED
            }
        }

        fun moveTo(y: Int) {
            val v = view ?: return
            val lp = v.layoutParams as WindowManager.LayoutParams
            if (lp.y == y) return
            lp.y = y
            runCatching { wm.updateViewLayout(v, lp) }
        }

        fun remove() {
            view?.let { runCatching { wm.removeView(it) } }
            view = null
            lifecycleRegistry.currentState = Lifecycle.State.DESTROYED
        }
    }
}

/**
 * Stand-in for B's `CallCheckCard` (#8), same signature, until it merges. Plain on purpose:
 * B owns the words and the look.
 */
@Composable
private fun CallCheckCardStub(state: CallCheckUi, onRing: () -> Unit, onCall: () -> Unit, onPickMember: (String) -> Unit, onClose: () -> Unit) {
    val check = state.check
    val who = check?.label ?: state.caller?.label
    Card(
        Modifier.fillMaxWidth().padding(12.dp),
        shape = RoundedCornerShape(20.dp),
        elevation = CardDefaults.cardElevation(8.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            val line = when {
                check == null && who == null -> "Says they're family? Check"
                check == null -> "Checking $who…"
                else -> when (check.outcome) {
                    Outcome.PENDING -> "Checking $who…"
                    Outcome.SAFE -> "✓ $who's phone"
                    Outcome.DANGER -> "✗ Not $who's phone" + if (check.spoofSuspected) " · caller ID may be faked" else ""
                    Outcome.UNKNOWN -> if (check.verdict == Verdict.CANT_REACH) "? Couldn't check $who" else "?"
                }
            }
            Text(line, style = MaterialTheme.typography.titleMedium)
            if (check == null && who == null) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    state.family.forEach { m -> OutlinedButton({ onPickMember(m.id) }) { Text(m.label) } }
                }
            }
            if (check != null && check.outcome in setOf(Outcome.DANGER, Outcome.UNKNOWN)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onRing) { Text("Ring $who") }
                    OutlinedButton(onCall) { Text("Call $who") }
                }
            }
            TextButton(onClose) { Text("Close") }
        }
    }
}
