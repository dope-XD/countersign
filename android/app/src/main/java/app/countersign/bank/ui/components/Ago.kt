package app.countersign.bank.ui.components

import android.text.format.DateUtils
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import app.countersign.bank.R

/** "Just now", "5 minutes ago", "Yesterday", in the phone's language. Never "0 minutes ago". */
@Composable
fun ago(at: Long, now: Long = System.currentTimeMillis()): String =
    if (now - at < DateUtils.MINUTE_IN_MILLIS) {
        stringResource(R.string.time_just_now)
    } else {
        DateUtils.getRelativeTimeSpanString(at, now, DateUtils.MINUTE_IN_MILLIS).toString()
    }
