package app.countersign.bank

import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.fragment.app.FragmentActivity
import app.countersign.bank.ui.AppRoot
import app.countersign.bank.ui.CsTheme
import app.countersign.bank.ui.Language

/** The whole app: sign-up the first time, then Home, Pay, Family and Profile, and the bank call. */
class MainActivity : FragmentActivity() {
    /** A family invite code from a scanned QR link (csbank://family?code=123456). */
    var inviteCode by mutableStateOf<String?>(null)

    // Android 12 doesn't apply the in-app language by itself (13+ does)
    override fun attachBaseContext(base: Context) = super.attachBaseContext(Language.wrap(base))

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        takeInvite(intent)
        CallWatchService.start(this)
        setContent { CsTheme { AppRoot(this) } }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        takeInvite(intent)
    }

    override fun onResume() {
        super.onResume()
        App.visible = true
    }

    override fun onPause() {
        App.visible = false
        super.onPause()
    }

    private fun takeInvite(i: Intent?) {
        val code = i?.data?.getQueryParameter("code")
        if (code != null && Regex("\\d{6}").matches(code)) inviteCode = code
    }
}
