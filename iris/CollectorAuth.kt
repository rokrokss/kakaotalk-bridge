package party.qwer.iris

import java.security.MessageDigest
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

object CollectorAuth {
    fun proof(challenge: String, token: String, build: String): String {
        require(Regex("[a-f0-9]{64}").matches(challenge))
        require(Regex("[A-Za-z0-9_-]{43}").matches(token))
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(token.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        return mac.doFinal("$challenge:$build".toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
    }

    fun accepts(header: String?, token: String): Boolean {
        if (!Regex("[A-Za-z0-9_-]{43}").matches(token)) return false
        val expected = "Bearer $token"
        if (header == null || header.length != expected.length) return false
        return MessageDigest.isEqual(header.toByteArray(Charsets.UTF_8), expected.toByteArray(Charsets.UTF_8))
    }
}
