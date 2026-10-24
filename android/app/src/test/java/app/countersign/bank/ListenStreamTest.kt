package app.countersign.bank

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ListenStreamTest {
    @Test
    fun readsTheServersVerdict() {
        val v = ListenStream.parseVerdict(
            """{"type": "listen_verdict", "level": "warn", "scam_type": "digital_arrest", "p_scam": 0.71, "cues": ["authority", "threat"], "abstain": false, "at": 1761300150.0}""",
        )!!
        assertEquals("warn", v.level)
        assertEquals("digital_arrest", v.type)
        assertEquals(listOf("authority", "threat"), v.cues)
    }

    @Test
    fun ignoresAbstainingOtherAndBrokenMessages() {
        assertNull(ListenStream.parseVerdict("""{"type": "listen_verdict", "level": "warn", "abstain": true}"""))
        assertNull(ListenStream.parseVerdict("""{"type": "hello"}"""))
        assertNull(ListenStream.parseVerdict("""{"type": "listen_verdict", "level": "panic"}"""))
        assertNull(ListenStream.parseVerdict("not json"))
    }

    @Test
    fun chunksPcmAsLittleEndian100msMessages() {
        val out = mutableListOf<ByteArray>()
        val chunks = PcmChunks(1600)
        repeat(9) { chunks.add(ShortArray(320) { i -> if (i == 0) 0x0102 else -1 }) { out += it } } // 9 × 20 ms
        assertEquals(1, out.size) // 180 ms: one full 100 ms chunk, the rest waits
        assertEquals(3200, out[0].size)
        assertArrayEquals(byteArrayOf(0x02, 0x01, -1, -1), out[0].copyOfRange(0, 4))
    }
}
