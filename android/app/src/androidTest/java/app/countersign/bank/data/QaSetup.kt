package app.countersign.bank.data

import android.os.Bundle
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import app.countersign.bank.CallWatchService
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Sets up an emulator for the QA script (docs/agents/platform.md) from the command line, leaving
 * the app signed in. Each step is one test, with its inputs as instrumentation args, e.g.:
 *
 *   adb -s emulator-5554 shell am instrument -w -e class app.countersign.bank.data.QaSetup#signUp \
 *       -e name Mom -e mobile 5555215554 app.countersign.bank.test/androidx.test.runner.AndroidJUnitRunner
 *
 * Steps: signUp (name, mobile, lang?), invite (prints the code), join (code, label),
 * confirm (label: confirms the first join request), home (prints it).
 */
@RunWith(AndroidJUnit4::class)
class QaSetup {
    private val repo = Repo.instance as RealRepository
    private val args: Bundle = InstrumentationRegistry.getArguments()

    private fun arg(name: String) = args.getString(name) ?: error("missing -e $name")

    private fun report(text: String) {
        Log.i("QaSetup", text)
        InstrumentationRegistry.getInstrumentation().sendStatus(0, Bundle().apply { putString("stream", "QaSetup: $text\n") })
    }

    @Test
    fun signUp() = runBlocking {
        val lang = if (args.getString("lang") == "hi") Lang.HI else Lang.EN
        val me = repo.signUp(arg("name"), arg("mobile"), lang)
        report("signed up ${me.id} ${me.mobile}")
    }

    @Test
    fun invite() = runBlocking { report("code ${repo.invite().code}") }

    @Test
    fun join() = runBlocking { repo.join(arg("code"), arg("label")) }

    @Test
    fun confirm() = runBlocking {
        repo.refresh()
        val r = repo.home.value!!.joinRequests.first()
        repo.confirmJoin(r.customerId, arg("label"))
        report("family ${repo.home.value!!.family.map { "${it.label}=${it.id}" }}")
    }

    @Test
    fun home() = runBlocking {
        repo.refresh()
        report("${repo.home.value}")
        CallWatchService.start(InstrumentationRegistry.getInstrumentation().targetContext)
    }
}
