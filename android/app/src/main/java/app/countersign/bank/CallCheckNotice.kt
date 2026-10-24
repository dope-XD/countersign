package app.countersign.bank

import android.app.KeyguardManager
import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.util.Log
import app.countersign.bank.data.CallCheckUi
import app.countersign.bank.data.Outcome
import app.countersign.bank.data.Repo
import app.countersign.bank.data.RingState
import app.countersign.bank.ui.Language
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * The call check as a heads-up notification, for when the phone is locked: Android hides every
 * app's overlay window while the lock screen is up, and the in-call screen keeps it up for the
 * whole call (#53). Heads-up notifications still show there. [Overlay] decides when.
 */
object CallCheckNotice {
    private const val ID = 7
    private const val ACTION_CHECK = "app.countersign.bank.CHECK"
    private const val ACTION_RING = "app.countersign.bank.RING"
    private const val EXTRA_ID = "id"

    /** What the notification last said: it only rings and pops up again when that changes. */
    private var lastSaid: String? = null

    fun locked(c: Context): Boolean = c.getSystemService(KeyguardManager::class.java).isKeyguardLocked

    fun show(app: Context, ui: CallCheckUi) {
        val c = Language.wrap(app) // Android 12: the in-app language (13+ applies it by itself)
        val check = ui.check
        val who = check?.label ?: ui.caller?.label
        val member = (check?.memberId ?: ui.caller?.id)?.let { id -> ui.family.firstOrNull { it.id == id } }
        val danger = check?.outcome == Outcome.DANGER
        val (title, text) = when {
            who == null -> c.getString(R.string.cc_pick_title) to c.getString(R.string.cc_pick_text)
            check == null -> c.getString(R.string.cc_checking, who) to null
            check.ring == RingState.RINGING -> c.getString(R.string.cc_ringing, who) to null
            check.ring == RingState.YES -> c.getString(R.string.cc_ring_yes, who) to null
            check.ring == RingState.NO -> c.getString(R.string.cc_ring_no, who) to c.getString(R.string.cc_danger_text)
            else -> when (check.outcome) {
                Outcome.PENDING -> c.getString(R.string.cc_checking, who) to null
                Outcome.SAFE -> c.getString(R.string.cc_safe, who) to null
                Outcome.DANGER -> c.getString(R.string.cc_danger, who) to c.getString(if (check.spoofSuspected) R.string.cc_spoof_text else R.string.cc_danger_text)
                Outcome.UNKNOWN -> c.getString(R.string.cc_cant_reach, who) to c.getString(R.string.cc_cant_reach_text)
            }
        }
        val b = Notification.Builder(c, Notify.CALL_CHECK)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(title)
            .setCategory(Notification.CATEGORY_CALL)
            .setVisibility(Notification.VISIBILITY_PUBLIC) // readable without unlocking: that's the point
            .setOngoing(true)
            .setOnlyAlertOnce(title == lastSaid)
        text?.let { b.setContentText(it).setStyle(Notification.BigTextStyle().bigText(it)) }
        when {
            danger -> b.setColor(Color.rgb(0xC6, 0x28, 0x28))
            check?.outcome == Outcome.SAFE -> b.setColor(Color.rgb(0x2E, 0x7D, 0x32))
        }
        if (who == null) {
            // an unknown number: one button per family member (a notification has room for three)
            ui.family.take(3).forEach { m -> b.addAction(action(c, m.label, broadcast(c, ACTION_CHECK, m.id))) }
        } else if (check != null && check.outcome in setOf(Outcome.DANGER, Outcome.UNKNOWN)) {
            if (check.ring == RingState.NONE || check.ring == RingState.NO_ANSWER) {
                b.addAction(action(c, c.getString(R.string.cc_action_ring, who), broadcast(c, ACTION_RING, check.id)))
            }
            member?.let { m ->
                val dial = Intent(Intent.ACTION_DIAL, Uri.parse("tel:${m.mobile}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                b.addAction(action(c, c.getString(R.string.cc_action_call, who), PendingIntent.getActivity(c, m.id.hashCode(), dial, PendingIntent.FLAG_IMMUTABLE)))
            }
        }
        lastSaid = title
        c.getSystemService(NotificationManager::class.java).notify(ID, b.build())
    }

    fun cancel(c: Context) {
        if (lastSaid == null) return
        lastSaid = null
        c.getSystemService(NotificationManager::class.java).cancel(ID)
    }

    private fun broadcast(c: Context, action: String, id: String) = PendingIntent.getBroadcast(
        c, (action + id).hashCode(), Intent(c, Actions::class.java).setAction(action).putExtra(EXTRA_ID, id),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    private fun action(c: Context, label: String, pi: PendingIntent) =
        Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(c, R.drawable.ic_notify), label, pi).build()

    /** The notification's buttons: check a member, or ring them. The answer comes back through the notification. */
    class Actions : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            val id = i.getStringExtra(EXTRA_ID) ?: return
            val done = goAsync()
            CoroutineScope(SupervisorJob() + Dispatchers.Main).launch {
                try {
                    when (i.action) {
                        ACTION_CHECK -> Repo.instance.check(id)
                        ACTION_RING -> Repo.instance.ring(id)
                    }
                } catch (e: Exception) {
                    Log.w("CallCheckNotice", "${i.action} failed: ${e.message}")
                } finally {
                    done.finish()
                }
            }
        }
    }
}
