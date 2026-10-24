package app.countersign.bank

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CallContextTest {
    @Test
    fun indianNumbersAreNotInternational() {
        listOf("+919812345678", "+91 98123 45678", "00919812345678", "9812345678", "09812345678", "5555215556", null, "")
            .forEach { assertFalse(it.toString(), CallContext.international(it)) }
    }

    @Test
    fun otherCountriesAre() {
        listOf("+14155550123", "+44 20 7946 0958", "0014155550123", "+9715012345678", "+92 300 1234567")
            .forEach { assertTrue(it, CallContext.international(it)) }
    }
}
