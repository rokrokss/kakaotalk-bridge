package party.qwer.iris

import java.util.Base64
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec

/** Only the two local database-key preferences are decoded. No preferences are modified. */
object ProfileData {
    private const val SALT = "userDbPassPhraseSalt"
    private const val FALLBACK = "userDbPassPhraseWhenFailed"

    private class Wire(val bytes: ByteArray, var pos: Int = 0, val end: Int = bytes.size) {
        fun integer(): Long {
            var value = 0L
            for (shift in 0..63 step 7) {
                require(pos < end)
                val byte = bytes[pos++].toInt() and 255
                if (shift == 63) require(byte <= 1)
                value = value or ((byte and 127).toLong() shl shift)
                if (byte and 128 == 0) return value
            }
            error("invalid_preference_integer")
        }
        fun block(): Wire {
            val length = integer()
            require(length in 0..(end - pos).toLong())
            val child = Wire(bytes, pos, pos + length.toInt())
            pos = child.end
            return child
        }
        fun text(): String = bytes.copyOfRange(pos, end).toString(Charsets.UTF_8)
        fun skip(type: Int) {
            when (type) {
                0 -> integer()
                1 -> { require(end - pos >= 8); pos += 8 }
                2 -> block()
                5 -> { require(end - pos >= 4); pos += 4 }
                else -> error("invalid_preference_wire_type")
            }
        }
    }

    fun passphrase(preferences: ByteArray): ByteArray {
        require(preferences.size in 1..4 * 1024 * 1024)
        var salt: Long? = null
        var fallback: String? = null
        val seen = mutableSetOf<String>()
        val root = Wire(preferences)
        while (root.pos < root.end) {
            val tag = root.integer().toInt()
            require(tag > 0)
            if (tag != 10) { root.skip(tag and 7); continue }
            val entry = root.block()
            var key: String? = null
            var value: Wire? = null
            while (entry.pos < entry.end) {
                val field = entry.integer().toInt()
                when (field) {
                    10 -> { require(key == null); key = entry.block().text() }
                    18 -> { require(value == null); value = entry.block() }
                    else -> { require(field > 0); entry.skip(field and 7) }
                }
            }
            if (key != SALT && key != FALLBACK) continue
            require(seen.add(key!!))
            val v = requireNotNull(value)
            if (key == SALT) {
                require(v.integer() == 32L)
                salt = v.integer()
            } else {
                require(v.integer() == 42L)
                fallback = v.block().text()
            }
            require(v.pos == v.end)
        }
        if (!fallback.isNullOrEmpty()) {
            // Android's Base64.DEFAULT allows line wrapping; reject every other nonalphabet byte.
            val encoded = fallback.filterNot { it == '\r' || it == '\n' || it == ' ' || it == '\t' }
            return Base64.getDecoder().decode(encoded).also { require(it.size == 32) }
        }
        require(salt != null && salt != 0L)
        val saltBytes = "se${salt}ed".toByteArray(Charsets.UTF_8).copyOf(16)
        val password = intArrayOf(4,15,81,123,77,5,23,99,2,111,10,31,54,29,109,97).map { it.toChar() }.toCharArray()
        val spec = PBEKeySpec(password, saltBytes, 4096, 256)
        return try { SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded }
        finally { spec.clearPassword(); password.fill('\u0000'); saltBytes.fill(0) }
    }

    data class Name(val value: String, val source: String)

    fun displayName(nickname: String, friend: String?, contact: String?, relation: Int): Name {
        if (relation != 9) {
            if (!friend.isNullOrBlank()) return Name(friend, "crypto_user.friend_nickname")
            if (!contact.isNullOrBlank()) return Name(contact, "crypto_user.contact_name")
        }
        return Name(nickname, "crypto_user.nickname")
    }
}
