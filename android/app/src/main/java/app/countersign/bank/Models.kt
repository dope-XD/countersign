package app.countersign.bank

import org.json.JSONObject

/** The bank's JSON (engine/mobile.py, engine/guard.py), as the screens use it. */

data class Account(
    val id: String,
    val name: String,
    val mobile: String,
    val accountNo: String,
    val upi: String,
    val card4: String,
    val balance: Double,
    val channel: String,
    val shareCallStatus: Boolean,
    val killSwitch: JSONObject?,
) {
    val firstName get() = name.substringBefore(' ')

    companion object {
        // the engine's "me" (#27) has no bank fields any more: the old screens show blanks until B replaces them
        fun from(o: JSONObject) = Account(
            o.getString("id"), o.getString("name"), o.getString("mobile"), o.optString("account_no"), o.optString("upi_id"),
            o.optString("card_last4"), o.optDouble("balance", 0.0), o.optString("check_channel", "ring"), o.optBoolean("share_call_status"), o.obj("kill_switch"),
        )
    }
}

data class FamilyMember(val id: String, val label: String, val name: String, val mobile: String, val upi: String, val since: Double) {
    companion object {
        fun from(o: JSONObject) = FamilyMember(o.getString("id"), o.getString("label"), o.getString("name"), o.getString("mobile"), o.optString("upi_id"), o.optDouble("since", 0.0))
    }
}

data class JoinRequest(val customerId: String, val name: String, val label: String) {
    companion object {
        fun from(o: JSONObject) = JoinRequest(o.getString("customer_id"), o.getString("name"), o.getString("label"))
    }
}

data class Approval(
    val id: String,
    val kind: String,
    val question: String,
    val detail: String,
    val challenge: String,
    val deliver: String,
    val expiresAt: Double,
    val status: String,
) {
    val isFamily get() = kind == "family_ping"

    companion object {
        fun from(o: JSONObject): Approval {
            val s = o.optJSONObject("summary") ?: o // the contract puts question and detail at the top
            return Approval(
                o.getString("id"), o.getString("kind"), s.optString("question"), s.optString("detail"), o.getString("challenge"),
                o.optString("deliver", "notify"), o.optDouble("expires_at", 0.0), o.optString("status", "pending"),
            )
        }
    }
}

data class MemberStatus(val shared: Boolean, val onCall: Boolean?, val callKind: String?, val seenSecondsAgo: Int?) {
    companion object {
        fun from(o: JSONObject?) = o?.let {
            MemberStatus(it.optBoolean("shared"), if (it.has("on_call")) it.optBoolean("on_call") else null, it.str("call_kind"), it.dbl("app_seen_s_ago")?.toInt())
        }
    }
}

data class FamilyOption(
    val id: String,
    val label: String,
    val name: String,
    val mobile: String,
    val upi: String,
    val newLink: Boolean,
    val simSwapped: Boolean,
    val status: MemberStatus?,
    val answer: String?,
) {
    companion object {
        fun from(o: JSONObject) = FamilyOption(
            o.getString("id"), o.getString("label"), o.getString("name"), o.getString("mobile"), o.getString("upi_id"),
            o.optBoolean("new_link"), o.optBoolean("sim_swapped_recently"), MemberStatus.from(o.optJSONObject("status")), o.str("answer"),
        )
    }
}

data class Payment(
    val id: String,
    val payee: String,
    val amount: Double,
    val amountText: String,
    val status: String,
    val reasons: List<String>,
    val tips: List<String>,
    val holdUntil: Double?,
    val redirectedTo: JSONObject?,
    val noAnswer: Boolean,
    val caseId: String?,
    val report: JSONObject?,
    val family: List<FamilyOption>,
    val createdAt: Double,
) {
    val open get() = status in setOf("confirm", "paused", "awaiting_family", "held")

    companion object {
        fun from(o: JSONObject): Payment {
            val g = o.obj("guard")
            fun list(name: String) = g?.optJSONArray(name)?.let { a -> (0 until a.length()).map { a.getString(it) } } ?: emptyList()
            return Payment(
                o.getString("id"), o.getString("payee"), o.getDouble("amount"), o.getString("amount_text"), o.getString("status"),
                list("reasons"), list("tips"), o.dbl("hold_until"), o.obj("redirected_to"), o.optBoolean("no_answer"),
                o.str("case_id"), o.obj("report"), o.getJSONArray("family").objects().map(FamilyOption::from), o.optDouble("created_at"),
            )
        }
    }
}

data class Home(
    val account: Account,
    val family: List<FamilyMember>,
    val joinRequests: List<JoinRequest>,
    val approvals: List<Approval>,
    val payments: List<Payment>,
    val bankCall: JSONObject?,
) {
    companion object {
        fun from(o: JSONObject) = Home(
            Account.from(o.obj("account") ?: o.getJSONObject("me")),
            o.getJSONArray("family").objects().map(FamilyMember::from),
            o.getJSONArray("join_requests").objects().map(JoinRequest::from),
            o.getJSONArray("approvals").objects().map(Approval::from),
            o.optJSONArray("payments")?.objects()?.map(Payment::from).orEmpty(),
            o.obj("bank_call"),
        )
    }
}
