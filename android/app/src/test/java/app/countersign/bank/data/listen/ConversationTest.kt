package app.countersign.bank.data.listen

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The phone's conversation check must give exactly what the engine's reference gives (conv_vectors.json, written by
 * `python -m engine.listener.conversation vectors`): token ids from Hugging Face's tokenizer, and whole calls replayed
 * with the real models' outputs recorded, so the logic is checked here without running the models.
 */
class ConversationTest {
    private fun asset(name: String) = File("src/main/assets/$name").readText()
    private val v = JSONObject(javaClass.classLoader!!.getResource("conv_vectors.json")!!.readText())
    private val tok by lazy { E5Tokenizer.parse(asset("e5_vocab.txt")) }
    private val cfg = ConvConfig(asset("conv.json"))
    private val matcher = Matcher(asset("moves.json"))
    private val rules = Rules.parse(asset("scam_patterns.json"))

    private fun JSONArray.strings() = (0 until length()).map { getString(it) }

    @Test
    fun tokenizerMatchesHuggingFace() {
        val cases = v.getJSONArray("tokenizer")
        val misses = mutableListOf<String>()
        for (i in 0 until cases.length()) {
            val c = cases.getJSONObject(i)
            val want = c.getJSONArray("ids").let { a -> (0 until a.length()).map { a.getLong(it) } }
            val got = tok.encode(c.getString("text")).toList()
            if (got != want) misses += "\"${c.getString("text").take(60)}\": $got vs $want"
        }
        assertTrue("${misses.size} of ${cases.length()} differ:\n" + misses.take(5).joinToString("\n"), misses.isEmpty())
    }

    @Test
    fun windowsAndSegmentsMatch() {
        val w = v.getJSONArray("windows")
        for (i in 0 until w.length()) {
            val c = w.getJSONObject(i)
            assertEquals(c.getString("window"), convWindow(c.getJSONArray("segments").strings()))
        }
        val s = v.getJSONArray("text_segments")
        for (i in 0 until s.length()) {
            val c = s.getJSONObject(i)
            assertEquals(c.getJSONArray("segments").strings(), textSegments(c.getString("text")))
        }
    }

    @Test
    fun accumulatorMatches() {
        val a = v.getJSONArray("accumulator")
        for (i in 0 until a.length()) {
            val c = a.getJSONObject(i)
            val ctx = c.getJSONArray("context").strings().toSet()
            val acc = Accumulator(cfg)
            val ps = c.getJSONArray("ps")
            val got = (0 until ps.length()).map { acc.feed(ps.getDouble(it), ctx) }
            assertEquals("case $i", c.getJSONArray("levels").strings(), got)
        }
    }

    @Test
    fun wholeCallsMatchTheEngine() {
        val calls = v.getJSONArray("calls")
        val misses = mutableListOf<String>()
        for (i in 0 until calls.length()) {
            val c = calls.getJSONObject(i)
            val p = c.getJSONObject("p")
            val emb = c.getJSONObject("emb")
            val models = object : ConvModels {
                override fun p(window: String) = p.getDouble(window)
                override fun embed(segment: String) = emb.getJSONArray(segment).let { a -> FloatArray(a.length()) { a.getDouble(it).toFloat() } }
            }
            val call = ConvCall(models, matcher, cfg, rules)
            call.context(c.getJSONArray("context").strings().toSet())
            var verdict = call.verdict()
            for (s in c.getJSONArray("segments").strings()) verdict = call.feed(s)
            val want = Verdict(c.getString("level"), c.getString("type"), c.getJSONArray("cues").strings(), c.getJSONArray("sources").strings())
            if (verdict != want) misses += "${c.getString("id")}: $verdict vs $want"
        }
        assertTrue(misses.joinToString("\n"), misses.isEmpty())
    }
}
