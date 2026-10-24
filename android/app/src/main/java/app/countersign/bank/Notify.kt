package app.countersign.bank

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.Ringtone
import android.media.RingtoneManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import org.json.JSONObject

/** Notifications: the ongoing "protected" one, family checks and approvals (ring or notify), and news. */
object Notify {
    const val WATCH = "watch"
    const val RING = "checks_ring"
    const val CHECKS = "checks"
    const val NEWS = "news"
    const val CALL_CHECK = "call_check"
    const val FAMILY_ALARM = "family_alarm"
    const val WATCH_ID = 1

    fun channels(c: Context) {
        val nm = c.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(WATCH, "Protection status", NotificationManager.IMPORTANCE_LOW))
        nm.createNotificationChannel(
            NotificationChannel(RING, "Family checks that ring", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "A family member or the bank needs your answer now. Rings like a call."
                setSound(
                    RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE),
                    AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE).build(),
                )
                enableVibration(true)
                vibrationPattern = longArrayOf(0, 800, 600, 800, 600, 800)
            },
        )
        nm.createNotificationChannel(
            NotificationChannel(CHECKS, "Family checks and approvals", NotificationManager.IMPORTANCE_HIGH).apply { enableVibration(true) },
        )
        nm.createNotificationChannel(
            NotificationChannel(CALL_CHECK, c.getString(R.string.channel_call_check), NotificationManager.IMPORTANCE_HIGH).apply {
                description = c.getString(R.string.channel_call_check_about)
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            },
        )
        nm.createNotificationChannel(NotificationChannel(NEWS, "Payments and alerts", NotificationManager.IMPORTANCE_DEFAULT))
        nm.createNotificationChannel(
            NotificationChannel(FAMILY_ALARM, c.getString(R.string.channel_family_alarm), NotificationManager.IMPORTANCE_HIGH).apply {
                description = c.getString(R.string.channel_family_alarm_about)
                setSound(
                    RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM),
                    AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM).build(),
                )
                enableVibration(true)
                vibrationPattern = longArrayOf(0, 1000, 500, 1000, 500, 1000)
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC
                setBypassDnd(true) // honoured once the user grants Do Not Disturb access
            },
        )
    }

    fun watch(c: Context, onCall: Boolean): Notification =
        Notification.Builder(c, WATCH)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(if (onCall) "On a call: payments are protected" else "CS Bank is protecting you")
            .setContentText("Family checks and bank approvals will reach you here.")
            .setOngoing(true)
            .setContentIntent(openApp(c, 0))
            .build()

    private fun openApp(c: Context, code: Int) =
        PendingIntent.getActivity(c, code, Intent(c, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE)

    /** A family check or bank approval. "ring" opens full screen like an incoming call; "notify" is a normal alert. */
    fun approval(c: Context, raw: JSONObject) {
        val a = Approval.from(raw)
        val nm = c.getSystemService(NotificationManager::class.java)
        val open = Intent(c, ApprovalActivity::class.java)
            .putExtra(ApprovalActivity.EXTRA, raw.toString())
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val pi = PendingIntent.getActivity(c, a.id.hashCode(), open, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val ring = a.deliver == "ring"
        val title = when (a.kind) {
            "family_ping", "call_check" -> "Family check: ${a.question}"
            "kill_switch_off" -> a.question
            else -> "CS Bank: ${a.question}"
        }
        val b = Notification.Builder(c, if (ring) RING else CHECKS)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(title)
            .setContentText(a.detail)
            .setStyle(Notification.BigTextStyle().bigText(a.detail))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .setCategory(if (ring) Notification.CATEGORY_CALL else Notification.CATEGORY_MESSAGE)
        if (ring && canRing(c)) b.setFullScreenIntent(pi, true)
        nm.notify(a.id.hashCode(), b.build())
        if (ring) {
            // Android only opens a full-screen alert by itself when the phone is locked or asleep, and may
            // silence the channel; so ring ourselves, and open the check at once if CS Bank is in front.
            Ringer.start(c)
            if (App.visible) c.startActivity(open)
        }
    }

    fun cancel(c: Context, approvalId: String) = c.getSystemService(NotificationManager::class.java).cancel(approvalId.hashCode())

    fun news(c: Context, title: String, body: String) {
        val n = Notification.Builder(c, NEWS)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(Notification.BigTextStyle().bigText(body))
            .setContentIntent(openApp(c, title.hashCode()))
            .setAutoCancel(true)
            .build()
        c.getSystemService(NotificationManager::class.java).notify(title.hashCode(), n)
    }

    private const val ALARM_ID = 7

    /** "Mummy may be on a scam call": full screen and ringing, like an incoming call (FamilyAlarmActivity). */
    fun familyAlarm(c: Context, a: app.countersign.bank.data.FamilyAlarmUi) {
        val open = Intent(c, FamilyAlarmActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val pi = PendingIntent.getActivity(c, ALARM_ID, open, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val title = c.getString(R.string.alarm_title, a.label)
        val b = Notification.Builder(c, FAMILY_ALARM)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(title)
            .setContentText(c.getString(R.string.alarm_notify_body))
            .setOngoing(true)
            .setContentIntent(pi)
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_ALARM)
        if (canRing(c)) b.setFullScreenIntent(pi, true)
        c.getSystemService(NotificationManager::class.java).notify(ALARM_ID, b.build())
        Ringer.alarm(c)
        if (App.visible) runCatching { c.startActivity(open) }
    }

    fun familyAlarmCleared(c: Context, label: String) {
        Ringer.stop()
        cancelAlarm(c)
        news(c, c.getString(R.string.alarm_cleared_title, label), c.getString(R.string.alarm_cleared_body, label))
    }

    fun cancelAlarm(c: Context) {
        Ringer.stop()
        c.getSystemService(NotificationManager::class.java).cancel(ALARM_ID)
    }

    /** Android 14+ lets the user (or Play) switch full-screen alerts off for an app. */
    fun canRing(c: Context): Boolean =
        Build.VERSION.SDK_INT < 34 || c.getSystemService(NotificationManager::class.java).canUseFullScreenIntent()
}

/** "Ring my phone": the ringtone, looping until the check is answered or opened (30 s at most). */
object Ringer {
    private var tone: Ringtone? = null
    private val main = Handler(Looper.getMainLooper())

    fun start(c: Context) {
        stop()
        tone = RingtoneManager.getRingtone(c.applicationContext, RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE))?.apply {
            audioAttributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE).build()
            isLooping = true
            play()
        }
        main.postDelayed({ stop() }, 30_000)
    }

    /**
     * The family scam alarm: the alarm sound at full alarm volume, looping, with strong vibration, for up to 3 minutes
     * or until they act. The alarm stream sounds even when the phone is on silent; with Do Not Disturb access it
     * also gets through Do Not Disturb.
     */
    fun alarm(c: Context) {
        stop()
        val app = c.applicationContext
        val am = app.getSystemService(android.media.AudioManager::class.java)
        runCatching { am.setStreamVolume(android.media.AudioManager.STREAM_ALARM, am.getStreamMaxVolume(android.media.AudioManager.STREAM_ALARM), 0) }
        val nm = app.getSystemService(android.app.NotificationManager::class.java)
        if (nm.isNotificationPolicyAccessGranted && nm.currentInterruptionFilter != android.app.NotificationManager.INTERRUPTION_FILTER_ALL) {
            previousFilter = nm.currentInterruptionFilter
            runCatching { nm.setInterruptionFilter(android.app.NotificationManager.INTERRUPTION_FILTER_ALARMS) }
        }
        tone = RingtoneManager.getRingtone(app, RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM))?.apply {
            audioAttributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM).build()
            isLooping = true
            play()
        }
        vibrator = app.getSystemService(android.os.VibratorManager::class.java).defaultVibrator.also {
            it.vibrate(android.os.VibrationEffect.createWaveform(longArrayOf(0, 1000, 500), 0))
        }
        nmRef = nm
        main.postDelayed({ stop() }, 180_000)
    }

    private var vibrator: android.os.Vibrator? = null
    private var previousFilter: Int? = null
    private var nmRef: android.app.NotificationManager? = null

    fun stop() {
        main.removeCallbacksAndMessages(null)
        tone?.stop()
        tone = null
        vibrator?.cancel()
        vibrator = null
        previousFilter?.let { f -> runCatching { nmRef?.setInterruptionFilter(f) } }
        previousFilter = null
    }
}
