package app.countersign.bank.data

import androidx.activity.ComponentActivity
import androidx.fragment.app.FragmentActivity
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow

/*
 * The only way screens (agent B) reach data and phone features (agent C).
 * Contract file: only agent A edits it, through a contract-change issue.
 *
 * Suspend functions throw an Exception whose message can be shown to the user as is.
 */
interface Repository {
    val signedIn: StateFlow<Boolean>

    /** Null until the first load after sign-in. Kept fresh from the events socket. */
    val home: StateFlow<Home?>

    /** The call on this phone right now, or null. */
    val call: StateFlow<LiveCall?>
    val permissions: StateFlow<Permissions>
    val events: SharedFlow<AppEvent>

    // ---- account
    suspend fun signUp(name: String, mobile: String, lang: Lang): Me

    suspend fun refresh()

    suspend fun setPrefs(lang: Lang? = null, channel: CheckChannel? = null, shareCallStatus: Boolean? = null): Me

    fun signOut()

    // ---- family
    suspend fun invite(): Invite

    /** [label] is what I call the person who invited me. */
    suspend fun join(code: String, label: String)

    /** [label] is what I call the person joining. */
    suspend fun confirmJoin(customerId: String, label: String)

    suspend fun declineJoin(customerId: String)

    suspend fun removeMember(memberId: String)

    // ---- calls
    /** "Says they're family? Check": the user picked who the caller claims to be. */
    suspend fun check(memberId: String): Check

    /** Ring the member: "Is it you on Mummy's call?". */
    suspend fun ring(checkId: String): Check

    /** Open the dialer with the member's saved number. */
    fun callMember(memberId: String)

    /** "I understand" on the pay guard. */
    suspend fun dismissScam()

    // ---- this phone's owner answering a ring; yes = fingerprint or screen lock first
    suspend fun answer(approvalId: String, yes: Boolean, activity: FragmentActivity): Approval

    // ---- permissions: opens the system prompt or settings page; [permissions] updates when the user comes back
    fun request(permission: Permission, activity: ComponentActivity)
}

/** Which repository the app uses. FakeRepository until C's RealRepository lands. */
object Repo {
    var instance: Repository = FakeRepository()
}
