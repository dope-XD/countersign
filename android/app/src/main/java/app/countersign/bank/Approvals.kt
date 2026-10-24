package app.countersign.bank

import androidx.fragment.app.FragmentActivity
import org.json.JSONObject

/** Answering a family check or bank approval. "Yes" is signed by this phone's key after the
 *  fingerprint or screen lock; "No" needs nothing, so anyone holding the phone can stop a payment. */
object Approvals {
    /** Returns an error to show, or null when the bank took the answer. */
    suspend fun decide(activity: FragmentActivity, a: Approval, approve: Boolean): String? = try {
        val body = JSONObject().put("decision", if (approve) "approve" else "decline")
        if (approve) {
            val subtitle = if (a.isFamily) "Confirm it was you who asked" else a.question
            body.put("signature", DeviceKey.sign(activity, DeviceKey.approvalMessage(a), "Confirm it's you", subtitle))
        }
        Api.post("/api/m/approvals/${a.id}/decide", body)
        Notify.cancel(activity, a.id)
        null
    } catch (e: DeviceKey.Cancelled) {
        "Not confirmed: ${e.message}"
    } catch (e: ApiError) {
        e.message
    }

    suspend fun load(id: String): Approval? = try {
        Api.get("/api/m/home").getJSONArray("approvals").objects().map(Approval::from).firstOrNull { it.id == id }
    } catch (e: ApiError) {
        null
    }
}
