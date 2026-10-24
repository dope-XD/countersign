package app.countersign.bank.data

import androidx.test.ext.junit.runners.AndroidJUnit4
import app.countersign.bank.Prefs
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.filterIsInstance
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.random.Random

/**
 * RealRepository against the dev server (BuildConfig.DEFAULT_SERVER): two new accounts, an invite,
 * a join (which reaches the inviter over the events socket), the confirm, and both homes.
 * Needs a screen lock on the device (`adb shell locksettings set-pin 1111`), for the sign-up key.
 *
 *   ./gradlew connectedDebugAndroidTest
 */
@RunWith(AndroidJUnit4::class)
class RealRepositoryTest {
    private val repo = Repo.instance as RealRepository

    private fun number() = "9" + (1..9).joinToString("") { Random.nextInt(10).toString() }

    private fun be(token: String, id: String) {
        Prefs.token = token
        Prefs.customerId = id
    }

    @Test
    fun signUpHomeAndFamily() = runBlocking {
        repo.signOut()

        val mom = repo.signUp("Test Mom", number(), Lang.HI)
        val momToken = Prefs.token!!
        assertEquals(mom, repo.home.value?.me)
        val invite = repo.invite()
        assertTrue(Regex("\\d{6}").matches(invite.code))
        repo.connect() // Mom's socket: the join request should reach it

        Prefs.signOut()
        val rahul = repo.signUp("Test Rahul", number(), Lang.EN)
        val rahulToken = Prefs.token!!
        val request = async { withTimeout(15_000) { repo.events.filterIsInstance<AppEvent.FamilyRequest>().first() } }
        repo.join(invite.code, "Mummy")
        assertEquals(rahul.id, request.await().customerId)

        be(momToken, mom.id)
        repo.refresh()
        val join = repo.home.value!!.joinRequests.single()
        assertEquals(rahul.id, join.customerId)
        assertEquals("Mummy", join.label)
        repo.confirmJoin(rahul.id, "Rahul")
        val linked = repo.home.value!!.family.single()
        assertEquals(rahul.id, linked.id)
        assertEquals("Rahul", linked.label)
        assertTrue(repo.home.value!!.joinRequests.isEmpty())

        be(rahulToken, rahul.id)
        repo.refresh()
        val mummy = repo.home.value!!.family.firstOrNull { it.id == mom.id }
        assertNotNull(mummy)
        assertEquals("Mummy", mummy!!.label)

        repo.removeMember(mom.id)
        assertTrue(repo.home.value!!.family.none { it.id == mom.id })
        repo.signOut()
    }
}
