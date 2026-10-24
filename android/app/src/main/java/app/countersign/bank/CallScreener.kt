package app.countersign.bank

import android.telecom.Call
import android.telecom.CallScreeningService

/**
 * Holds ROLE_CALL_SCREENING only to read who is calling. Every call is let through, untouched:
 * the number goes to [FamilyNumbers] on this phone and nowhere else.
 */
class CallScreener : CallScreeningService() {
    override fun onScreenCall(details: Call.Details) {
        if (details.callDirection == Call.Details.DIRECTION_INCOMING) {
            FamilyNumbers.sawIncoming(details.handle?.schemeSpecificPart)
        }
        respondToCall(details, CallResponse.Builder().build())
    }
}
