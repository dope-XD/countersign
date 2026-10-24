package app.countersign.bank

import android.net.Uri
import android.telecom.CallRedirectionService
import android.telecom.PhoneAccountHandle

/**
 * Holds ROLE_CALL_REDIRECTION only to read the number this phone is dialling. It never
 * redirects: every call goes out as dialled, and the number stays in [FamilyNumbers].
 */
class CallRedirector : CallRedirectionService() {
    override fun onPlaceCall(handle: Uri, initialPhoneAccount: PhoneAccountHandle, allowInteractiveResponse: Boolean) {
        FamilyNumbers.sawOutgoing(handle.schemeSpecificPart)
        placeCallUnmodified()
    }
}
