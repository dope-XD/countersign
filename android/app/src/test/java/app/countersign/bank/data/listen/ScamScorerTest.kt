package app.countersign.bank.data.listen

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The phone's scorer must give exactly what the engine's reference gives on every shared transcript. */
class ScamScorerTest {
    private val rules = Rules.parse(File("src/main/assets/scam_patterns.json").readText())
    private val fusion = FusionConfig.parse(File("src/main/assets/fusion.json").readText())
    private val transcripts = JSONObject(javaClass.classLoader!!.getResource("scam_transcripts.json")!!.readText()).getJSONArray("transcripts")

    private fun run(t: JSONObject): Verdict {
        val ctx = t.getJSONArray("context").let { a -> (0 until a.length()).map { a.getString(it) }.toSet() }
        val s = CallScorer(rules)
        var prev = "none"
        val turns = t.getJSONArray("turns")
        for (i in 0 until turns.length()) {
            s.feed(turns.getString(i))
            prev = fuse(s.result(), rules, fusion, ctx, prev = prev).level
        }
        return fuse(s.result(), rules, fusion, ctx, prev = prev)
    }

    @Test
    fun matchesTheEngineOnEverySharedTranscript() {
        val misses = mutableListOf<String>()
        for (i in 0 until transcripts.length()) {
            val t = transcripts.getJSONObject(i)
            val e = t.getJSONObject("expect")
            val want = Triple(e.getString("level"), e.getString("type"), e.getJSONArray("categories").let { a -> (0 until a.length()).map { a.getString(it) } })
            val v = run(t)
            if (Triple(v.level, v.type, v.cues) != want) misses += "${t.getString("id")}: got ${v.level}/${v.type}/${v.cues}, engine $want"
        }
        assertTrue(misses.joinToString("\n"), misses.isEmpty())
    }

    @Test
    fun normalizeKeepsDevanagariMarks() {
        assertEquals(listOf("किसी", "को", "मत", "बताना"), normalize("किसी को मत बताना!"))
        assertEquals(listOf("dont", "tell", "anyone"), normalize("Don't tell, ANYONE."))
    }

    @Test
    fun negationAfterTheWordIsWaitedFor() {
        val s = CallScorer(rules)
        s.feed("please tell me the OTP")
        assertTrue("credentials" in s.result().categories)
        s.feed("never to anyone, the bank never asks")
        assertFalse("credentials" in s.result().categories)
    }

    @Test
    fun oneKeywordNeverMakesScam() {
        val s = CallScorer(rules)
        assertEquals("watch", fuse(s.feed("please share the OTP"), rules, fusion, setOf("unknown_number")).level)
    }
}
