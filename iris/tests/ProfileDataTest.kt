package party.qwer.iris

import org.junit.Assert.*
import org.junit.Test
import java.util.Base64

class ProfileDataTest {
    private fun integer(v: Long): ByteArray {
        var n = v
        val out = mutableListOf<Byte>()
        do {
            var byte = (n and 127).toInt()
            n = n ushr 7
            if (n != 0L) byte = byte or 128
            out.add(byte.toByte())
        } while (n != 0L)
        return out.toByteArray()
    }
    private fun bytes(v: ByteArray) = integer(v.size.toLong()) + v
    private fun entry(key: String, value: ByteArray): ByteArray = byteArrayOf(10) + bytes(
        byteArrayOf(10) + bytes(key.toByteArray()) + byteArrayOf(18) + bytes(value)
    )
    private fun salt(n: Long) = entry("userDbPassPhraseSalt", byteArrayOf(32) + integer(n))
    private fun fallback(s: String) = entry("userDbPassPhraseWhenFailed", byteArrayOf(42) + bytes(s.toByteArray()))
    private fun invalid(bytes: ByteArray) { assertThrows(Exception::class.java) { ProfileData.passphrase(bytes) } }

    @Test fun explicitNameWins() {
        assertEquals(ProfileData.Name("Chosen", "crypto_user.friend_nickname"), ProfileData.displayName("Nick","Chosen","Contact",1))
    }
    @Test fun blankOverrideUsesContact() {
        assertEquals(ProfileData.Name("Contact", "crypto_user.contact_name"), ProfileData.displayName("Nick"," \t","Contact",1))
    }
    @Test fun missingOverridesUseProfile() {
        assertEquals(ProfileData.Name("Nick", "crypto_user.nickname"), ProfileData.displayName("Nick",null,"  ",1))
    }
    @Test fun deactivatedUsesProfileName() {
        assertEquals(ProfileData.Name("Nick", "crypto_user.nickname"), ProfileData.displayName("Nick","Chosen","Contact",9))
    }
    @Test fun fallbackUsesExactBytesBeforeSalt() {
        val key = ByteArray(32) { it.toByte() }
        val encoded = Base64.getEncoder().encodeToString(key)
        assertArrayEquals(key,ProfileData.passphrase(salt(42)+fallback(encoded.take(20)+"\n"+encoded.drop(20))))
    }
    @Test fun missingOrInvalidKeyMaterialFailsClosed() {
        invalid(salt(0)); invalid(byteArrayOf()); invalid(fallback("bad")); invalid(salt(3)+fallback("not-valid"))
        invalid(entry("unrelated",byteArrayOf(32,4)))
    }
    @Test fun duplicateAndWrongTypedPreferencesFailClosed() {
        invalid(salt(3)+salt(4))
        invalid(entry("userDbPassPhraseSalt",byteArrayOf(42,1,49)))
        invalid(salt(2)+fallback(" "))
    }
    @Test fun truncatedAndOversizedWireValuesFailClosed() {
        invalid(salt(3).dropLast(1).toByteArray())
        invalid(byteArrayOf(10,127,1))
        invalid(byteArrayOf(10,0x80.toByte()))
        invalid(byteArrayOf(0))
        invalid(ByteArray(4*1024*1024+1))
    }
    @Test fun otherPreferenceValuesAreIgnored() {
        assertArrayEquals(ProfileData.passphrase(salt(123)),ProfileData.passphrase(entry("unrelated",byteArrayOf(42,2,1,2))+salt(123)))
    }
    @Test fun pbkdf2MatchesIndependentPositiveAndNegativeSeedVectors() {
        for ((seed,hex) in listOf(
            123456789L to "5fd080ddf6bae02950689ec3e6099a86ef778fa6600e9d81238ef8ab039b9d7a",
            -123456789L to "451cff6fbe0ed498d80e5fcb2f1676c81e280b149a0e1521628f305411ba0cb6"
        )) {
            val input = salt(seed) + fallback("")
            val original = input.clone()
            assertEquals(hex,ProfileData.passphrase(input).joinToString("") { "%02x".format(it) })
            assertArrayEquals(original,input)
        }
    }
}
