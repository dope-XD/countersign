package app.countersign.bank

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import app.countersign.bank.data.Repo
import app.countersign.bank.ui.CsTheme
import app.countersign.bank.ui.FamilyAlarmScreen

/** "Mummy may be on a scam call", full screen and over the lock screen (Notify.familyAlarm opens it and rings). */
class FamilyAlarmActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val repo = Repo.instance
        setContent {
            val alarm by repo.alarm.collectAsState()
            LaunchedEffect(alarm) { if (alarm == null) finish() }
            val a = alarm ?: return@setContent
            CsTheme {
                FamilyAlarmScreen(
                    a,
                    onCall = {
                        Ringer.stop()
                        repo.callMember(a.memberId)
                    },
                    onMessage = {
                        Ringer.stop()
                        repo.messageMember(a.memberId)
                    },
                    onDismiss = {
                        repo.dismissAlarm()
                        finish()
                    },
                )
            }
        }
    }

    override fun onStop() {
        super.onStop()
        Ringer.stop()
    }
}
