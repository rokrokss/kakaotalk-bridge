package party.qwer.iris

import org.junit.Assert.*
import org.junit.Test

class CollectorAuthTest {
    @Test fun onlyExactProvisionedBearerIsAccepted() {
        val token = "a".repeat(43)
        assertTrue(CollectorAuth.accepts("Bearer $token", token))
        for (header in listOf(null, "", token, "Bearer " + "b".repeat(43), "Bearer $token ", "bearer $token")) {
            assertFalse(CollectorAuth.accepts(header, token))
        }
        assertFalse(CollectorAuth.accepts("Bearer ", ""))
        assertFalse(CollectorAuth.accepts("Bearer $token", "a".repeat(42)))
    }
}
