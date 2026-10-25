package app.countersign.bank

import android.content.Intent
import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.fragment.app.FragmentActivity
import app.countersign.bank.data.RealRepository
import app.countersign.bank.data.Repo
import app.countersign.bank.ui.AppRoot
import app.countersign.bank.ui.CsTheme

/** The whole app: sign-up the first time, then Home, Pay, Family and Profile, and the bank call. */
class MainActivity : FragmentActivity() {
    /** A family invite code from a scanned QR link (csbank://family?code=123456). */
    var inviteCode by mutableStateOf<String?>(null)

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

    // A permission Android grants without a dialog (same group as one already granted) never pauses this activity, so
    // onResume's check doesn't run: check again whenever a request or a role prompt answers (#91).
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        (Repo.instance as? RealRepository)?.checkPermissions()
    }

    @Deprecated("The role prompt is started with startActivityForResult")
    @Suppress("DEPRECATION")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        (Repo.instance as? RealRepository)?.checkPermissions()
    }

    private fun takeInvite(i: Intent?) {
        val code = i?.data?.getQueryParameter("code")
        if (code != null && Regex("\\d{6}").matches(code)) inviteCode = code
    }
}
