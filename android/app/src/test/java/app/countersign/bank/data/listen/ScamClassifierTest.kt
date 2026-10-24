package app.countersign.bank.data.listen

import org.json.JSONArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The phone's classifier must give exactly what the engine's reference gives on the shared vectors (clf_vectors.json). */
class ScamClassifierTest {
    private val clf = ScamClassifier.load(File("src/main/assets/scam_clf.bin").readBytes(), File("src/main/assets/scam_clf.json").readText())
    private val vectors = JSONArray(javaClass.classLoader!!.getResource("clf_vectors.json")!!.readText())

    @Test
    fun matchesTheEngineOnEverySharedVector() {
        val misses = mutableListOf<String>()
        for (i in 0 until vectors.length()) {
            val v = vectors.getJSONObject(i)
            if (v.has("fnv1a")) {
                val h = v.getJSONObject("fnv1a")
                for (s in h.keys()) assertEquals("fnv1a($s)", h.getLong(s), fnv1a(s))
                continue
            }
            val text = v.getString("text")
            val wantTokens = v.getJSONArray("tokens").let { a -> (0 until a.length()).map { a.getString(it) } }
            if (clfTokens(text) != wantTokens) misses += "tokens of \"$text\": ${clfTokens(text)} vs $wantTokens"
            val want = v.getJSONObject("features").let { o -> o.keys().asSequence().associate { it.toInt() to o.getDouble(it) } }
            val got = vectorize(text, clf.dim, 2, 5)
            if (got.keys != want.keys || got.any { (k, x) -> kotlin.math.abs(x - want.getValue(k)) > 1e-6 }) misses += "features of \"$text\""
            if (kotlin.math.abs(clf.pScam(text) - v.getDouble("p_scam")) > 1e-5) misses += "p_scam of \"$text\": ${clf.pScam(text)} vs ${v.getDouble("p_scam")}"
        }
        assertTrue(misses.joinToString("\n"), misses.isEmpty())
    }

    @Test
    fun foldsDevanagariAsHinglishIsTyped() {
        assertEquals("pulis", fold("पुलिस"))
        assertEquals("khata", fold("खाता"))
        assertEquals("baink", fold("बैंक"))
        assertEquals("police", fold("police"))
    }

    @Test
    fun abstainsOnAFewWords() {
        assertTrue(clf.judge("hello ji").abstain)
        assertTrue(!clf.judge("hello ji", minWords = 1).abstain)
    }
}
