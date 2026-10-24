package app.countersign.bank

import app.countersign.bank.data.Member
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class FamilyNumbersTest {
    private fun member(id: String, mobile: String) = Member(id, id, id, mobile, 0, online = true, newLink = false)

    private val family = listOf(member("rahul", "+919812345678"), member("emu", "+915555215556"))

    @Test
    fun matchesOnTheLastTenDigits() {
        assertEquals("rahul", FamilyNumbers.match("09812345678", family)?.id)
        assertEquals("rahul", FamilyNumbers.match("+91 98123-45678", family)?.id)
        assertEquals("rahul", FamilyNumbers.match("9812345678", family)?.id)
        assertEquals("emu", FamilyNumbers.match("5555215556", family)?.id) // adb emu gsm call
    }

    @Test
    fun otherNumbersAreNobody() {
        assertNull(FamilyNumbers.match("9000000001", family))
        assertNull(FamilyNumbers.match("12345", family))
        assertNull(FamilyNumbers.match(null, family))
        assertNull(FamilyNumbers.match("", family))
    }
}
