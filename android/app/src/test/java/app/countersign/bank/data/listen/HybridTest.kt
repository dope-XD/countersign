package app.countersign.bank.data.listen

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The two judges together (Hybrid.kt), the smarter check's words (Llm.kt) and the digits-read-out signal must give what
 * the engine's reference gives (engine/listener/hybrid.py, llm.py): hybrid_vectors.json replays whole calls with the
 * conversation models' recorded outputs (from conv_vectors.json), context and smarter-check answers; llm_vectors.json
 * holds prompts and parsed model outputs.
 */
class HybridTest {
    private fun asset(name: String) = File("src/main/assets/$name").readText()
    private fun resource(name: String) = javaClass.classLoader!!.getResource(name)!!.readText()
    private fun JSONArray.strings() = (0 until length()).map { getString(it) }

    private val rules = Rules.parse(asset("scam_patterns.json"))
    private val fusion = FusionConfig.parse(asset("fusion.json"))
    private val clf = ScamClassifier.load(File("src/main/assets/scam_clf.bin").readBytes(), asset("scam_clf.json"))
    private val conv = JSONObject(resource("conv_vectors.json")).getJSONArray("calls").let { a -> (0 until a.length()).associate { a.getJSONObject(it).let { c -> c.getString("id") to c } } }

    private fun analyzer(id: String): Analyzer {
        val c = conv.getValue(id)
        val p = c.getJSONObject("p")
        val emb = c.getJSONObject("emb")
        val models = object : ConvModels {
            override fun p(window: String) = p.getDouble(window)
            override fun embed(segment: String) = emb.getJSONArray(segment).let { a -> FloatArray(a.length()) { a.getDouble(it).toFloat() } }
        }
        return Analyzer(rules, fusion, clf, conv = ConvKit(models, Matcher(asset("moves.json")), ConvConfig(asset("conv.json"))))
    }

    private fun llm(o: JSONObject?) = o?.let { LlmVerdict(it.getString("verdict"), it.getString("type"), it.getString("reason_en"), it.getString("reason_hi")) }

    @Test
    fun wholeCallsMatchTheEngine() {
        val vectors = JSONArray(resource("hybrid_vectors.json"))
        val misses = mutableListOf<String>()
        for (i in 0 until vectors.length()) {
            val v = vectors.getJSONObject(i)
            val call = analyzer(v.getString("id")).call()
            call.context(v.getJSONArray("context").strings().toSet())
            val l = llm(v.optJSONObject("llm"))
            val segs = v.getJSONArray("segments").strings()
            val levels = segs.mapIndexed { k, s ->
                call.feed(s)
                if (l != null && k == segs.size / 2) call.llm(l)
                call.verdict.level
            }
            val got = listOf(levels, call.verdict.level, call.verdict.type, call.verdict.cues, call.verdict.sources, call.shown?.reasonEn)
            val want = listOf(v.getJSONArray("levels").strings(), v.getString("level"), v.getString("type"), v.getJSONArray("cues").strings(), v.getJSONArray("sources").strings(), if (v.isNull("reason")) null else v.getString("reason"))
            if (got != want) misses += "${v.getString("id")}: $got vs $want"
        }
        assertTrue("${misses.size} differ:\n" + misses.take(5).joinToString("\n"), misses.isEmpty())
    }

    @Test
    fun promptsAndParsingMatchTheEngine() {
        val v = JSONObject(resource("llm_vectors.json"))
        val template = asset("llm_prompt.txt")
        val prompts = v.getJSONArray("prompts")
        for (i in 0 until prompts.length()) {
            val c = prompts.getJSONObject(i)
            assertEquals("prompt $i", c.getString("prompt"), llmPrompt(template, c.getString("transcript"), c.getJSONArray("signals").strings().toSet()))
        }
        val parse = v.getJSONArray("parse")
        for (i in 0 until parse.length()) {
            val c = parse.getJSONObject(i)
            val want = if (c.isNull("parsed")) null else llm(c.getJSONObject("parsed"))
            assertEquals(c.getString("output"), want, parseLlm(c.getString("output")))
        }
    }

    @Test
    fun digitsReadOut() {
        assertEquals(listOf(4), digitRuns(normalize("my otp is 4 5 2 1 okay")))
        assertEquals(listOf(4), digitRuns(normalize("char paanch do ek")))
        assertEquals(listOf(6), digitRuns(normalize("चार पांच दो एक सात आठ")))
        assertTrue(digitsReadOut(normalize("it is 452 189")))
        assertTrue(!digitsReadOut(normalize("call me on 9876543210")))
        assertTrue("digits_read_out" in derivedContext(setOf("unknown_number"), normalize("4 5 2 1"), emptySet()))
        assertTrue("digits_read_out" !in derivedContext(setOf("known_contact"), normalize("4 5 2 1"), emptySet()))
        assertTrue("bank_claim_not_1600" in derivedContext(setOf("unknown_number"), emptyList(), setOf("verification_pretext")))
        assertTrue("bank_claim_not_1600" !in derivedContext(setOf("unknown_number", "series_1600"), emptyList(), setOf("verification_pretext")))
    }

    private fun v(level: String, vararg sources: String, alone: Boolean = false) = Verdict(level, "unknown", listOf("authority"), sources.toList().ifEmpty { listOf("cues") }, alone)
    private val none = Verdict("none", "unknown", emptyList(), emptyList())
    private val scam = LlmVerdict("scam", "digital_arrest", "They threaten arrest and ask for money.", "वे पैसे मांग रहे हैं।")

    @Test
    fun scamNeedsTwoIndependentSources() {
        assertEquals("warn", combine(none, v("scam", "phone_ai"), "scam").verdict.level) // the conversation model alone
        assertEquals("scam", combine(v("warn"), v("scam", "phone_ai"), "scam").verdict.level)
        assertEquals("scam", combine(none, v("scam", "phone_ai"), "scam", llm = scam).verdict.level)
        assertEquals("warn", combine(v("scam", alone = true), none, "none").verdict.level) // the cue words alone
        assertEquals("scam", combine(v("scam", alone = true), v("watch", "phone_ai"), "watch").verdict.level)
        assertEquals("scam", combine(v("scam", alone = true), null).verdict.level) // basic mode: as before
        assertEquals("scam", combine(v("scam", "cues", "context"), none, "none").verdict.level)
    }

    @Test
    fun theSmarterCheckRaisesWarnNeverLowersAndItsReasonShows() {
        val r = combine(v("warn"), none, "watch", llm = scam)
        assertEquals("scam", r.verdict.level)
        assertTrue("llm" in r.verdict.sources)
        assertEquals(scam.reason, r.shown?.reason)
        assertEquals("watch", combine(v("watch"), none, "watch", llm = scam).verdict.level)
        val quiet = combine(v("warn"), none, "watch", llm = LlmVerdict("ok"), prev = "warn")
        assertEquals("warn", quiet.verdict.level)
        assertNull(quiet.shown)
        val reasonOnly = combine(v("warn"), none, "watch", llm = scam, llmCanRaise = false)
        assertEquals("warn", reasonOnly.verdict.level)
        assertEquals(scam, reasonOnly.shown)
    }

    @Test
    fun aContextSignalCountsOnce() {
        val f = FusionConfig.parse(asset("fusion.json"))
        val one = CallScorer(rules).feed("please share the OTP")
        assertEquals("warn", fuse(one, rules, f, setOf("unknown_number", "international_number")).level)
        val said = CallScorer(rules).feed("this is the police, there is a warrant, transfer the money")
        assertEquals("warn", fuse(said, rules, f).level)
        val r = fuse(said, rules, f, setOf("international_number"))
        assertEquals("scam", r.level)
        assertTrue(!r.alone && "context" in r.sources)
    }
}
