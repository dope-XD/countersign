package app.countersign.bank.data.listen

import app.countersign.bank.data.RiskLevel
import org.json.JSONArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The phone's Analyzer must give what the engine's reference (engine/listener/analyzer.py) gives on the shared vectors. */
class AnalyzerTest {
    private val analyzer = Analyzer(
        Rules.parse(File("src/main/assets/scam_patterns.json").readText()),
        FusionConfig.parse(File("src/main/assets/fusion.json").readText()),
        ScamClassifier.load(File("src/main/assets/scam_clf.bin").readBytes(), File("src/main/assets/scam_clf.json").readText()),
    )
    private val vectors = JSONArray(javaClass.classLoader!!.getResource("analyzer_vectors.json")!!.readText())

    private fun JSONArray.strings() = (0 until length()).map { getString(it) }

    @Test
    fun matchesTheEngineOnEverySharedVector() {
        val misses = mutableListOf<String>()
        for (i in 0 until vectors.length()) {
            val v = vectors.getJSONObject(i)
            val voice = if (v.isNull("voice")) null else v.getDouble("voice").toFloat()
            val a = analyzer.text(v.getString("text"), v.getJSONArray("context").strings().toSet(), voice)
            val want = listOf(v.getString("level"), v.getString("type"), v.getJSONArray("cues").strings().toString(), v.getJSONArray("sources").strings().sorted().toString())
            val got = listOf(a.level.wire, a.type.wire, a.cues.toString(), a.sources.map { it.wire }.sorted().toString())
            if (got != want) misses += "${v.getString("id")}: $got vs $want"
        }
        assertTrue(misses.joinToString("\n"), misses.isEmpty())
    }

    @Test
    fun aLiveCallClimbsAndNotAScamSilencesIt() {
        val c = analyzer.call()
        c.feed("hello madam this is inspector sharma from mumbai police crime branch")
        c.feed("there is an arrest warrant in your name for money laundering, do not tell anyone, stay on the video call")
        c.feed("transfer all the money in your account to the safe RBI account now for verification")
        assertEquals("scam", c.verdict.level)
        c.clear()
        assertEquals("none", c.feed("send it now").level)
        assertTrue(c.cleared)
    }

    @Test
    fun anAiVoiceAloneWarnsButNeverMakesScam() {
        val a = analyzer.text("hello ji how are you, I am calling about the function next week, are you coming", voiceClone = 0.95f)
        assertEquals(RiskLevel.WARN, a.level)
        assertTrue("synthetic_voice" in a.cues)
        assertNotEquals(RiskLevel.SCAM, analyzer.text("hello ji how are you", voiceClone = 0.99f).level)
    }
}
