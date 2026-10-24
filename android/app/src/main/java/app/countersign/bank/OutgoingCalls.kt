package app.countersign.bank

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * The number this phone is dialling, from the NEW_OUTGOING_CALL broadcast (PROCESS_OUTGOING_CALLS).
 * It only reads: it never sets a result, so it can't change or cancel the call (a call
 * redirection role could, on a slow phone). The number stays in [FamilyNumbers].
 */
class OutgoingCalls : BroadcastReceiver() {
    @Suppress("DEPRECATION") // still delivered on every Android version we support
    override fun onReceive(c: Context, i: Intent) {
        if (i.action == Intent.ACTION_NEW_OUTGOING_CALL) FamilyNumbers.sawOutgoing(i.getStringExtra(Intent.EXTRA_PHONE_NUMBER))
    }
}
