package app.countersign.bank

import app.countersign.bank.data.RiskLevel
import app.countersign.bank.data.RiskSource
import app.countersign.bank.data.ScamType
import app.countersign.bank.data.listen.FusionConfig
import app.countersign.bank.data.listen.Rules
import app.countersign.bank.data.listen.Verdict
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class CallRiskTest {
    private val rules = Rules.parse(File("src/main/assets/scam_patterns.json").readText())
    private val fusion = FusionConfig.parse(File("src/main/assets/fusion.json").readText())
    private var clock = 1_000_000L
    private val risk = CallRisk(rules, fusion) { clock }

    @Test
    fun quietCallHasNoRisk() = assertNull(risk.risk())

    @Test
    fun aFailedCallerCheckAloneWarns() {
        risk.context(setOf("caller_check_failed"))
        val r = risk.risk()!!
        assertEquals(RiskLevel.WARN, r.level)
        assertEquals(ScamType.IMPERSONATION, r.type)
        assertTrue(RiskSource.CALLER_CHECK in r.sources)
    }

    @Test
    fun theServersVerdictDecidesWhileFresh() {
        risk.server(Verdict("scam", "digital_arrest", listOf("authority", "threat"), emptyList()))
        val r = risk.risk()!!
        assertEquals(RiskLevel.SCAM, r.level)
        assertEquals(ScamType.DIGITAL_ARREST, r.type)
        assertTrue(RiskSource.SERVER in r.sources)
        assertEquals(clock, r.since)
    }

    @Test
    fun theLevelNeverGoesDownEvenWhenTheVerdictGoesStale() {
        risk.server(Verdict("warn", "bank_kyc", emptyList(), emptyList()))
        assertEquals(RiskLevel.WARN, risk.risk()!!.level)
        val since = clock
        clock += (fusion.serverFreshS + 1) * 1000L
        risk.server(Verdict("none", "unknown", emptyList(), emptyList()))
        val r = risk.risk()!!
        assertEquals(RiskLevel.WARN, r.level)
        assertEquals(since, r.since)
    }

    @Test
    fun alertFamilyIsAlwaysScam() {
        risk.alertFamily()
        risk.server(Verdict("none", "unknown", emptyList(), emptyList()))
        assertEquals(RiskLevel.SCAM, risk.risk()!!.level)
    }
}
