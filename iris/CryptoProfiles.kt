package party.qwer.iris

import android.os.Build
import android.system.Os
import android.system.OsConstants
import net.zetetic.database.DatabaseErrorHandler
import net.zetetic.database.sqlcipher.SQLiteDatabase
import java.io.Closeable
import java.io.File
import java.security.MessageDigest
import java.util.zip.ZipFile

/** SQLCipher profile reader. The source DB is always opened read-only, without a Room helper. */
class CryptoProfiles private constructor(private val db: SQLiteDatabase, private val password: ByteArray) : Closeable {
    companion object {
        private const val ROOT = "/data/user/0/com.kakao.talk"
        private var loaded = false

        @Synchronized private fun loadNative() {
            if (loaded) return
            val apk = System.getProperty("java.class.path").split(':').first { it.endsWith(".apk") }
            val directory = File("/data/local/tmp/kakaocollector-native")
            if (!directory.exists()) require(directory.mkdir())
            val stat = Os.lstat(directory.path)
            require(OsConstants.S_ISDIR(stat.st_mode) && stat.st_uid == 0)
            Os.chmod(directory.path, 448) // 0700, no other app may replace the library.
            ZipFile(apk).use { zip ->
                val entry = Build.SUPPORTED_ABIS.firstNotNullOfOrNull { zip.getEntry("lib/$it/libsqlcipher.so") }
                    ?: error("profile_native_abi_unavailable")
                require(entry.size in 1..32 * 1024 * 1024)
                val bytes = zip.getInputStream(entry).use { it.readBytes() }
                require(bytes.size.toLong() == entry.size)
                val hash = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
                val library = File(directory, "$hash.so")
                // Always use the APK's bytes, even if an earlier process left a file at this path.
                val temporary = File.createTempFile("sqlcipher-", ".tmp", directory)
                try {
                    temporary.writeBytes(bytes)
                    Os.chmod(temporary.path, 320) // 0500
                    Os.rename(temporary.path, library.path)
                    System.load(library.path)
                    loaded = true
                } finally { temporary.delete() }
            }
        }

        fun open(): CryptoProfiles {
            loadNative()
            val preferences = File("$ROOT/files/datastore/Feature_DataStore.pref.preferences_pb")
            require(preferences.length() in 1..4 * 1024 * 1024)
            val bytes = preferences.readBytes()
            val password = try { ProfileData.passphrase(bytes) } finally { bytes.fill(0) }
            var database: SQLiteDatabase? = null
            try {
                // The library's default corruption handler can delete a DB. Never use it here.
                val handler = DatabaseErrorHandler { _, _ -> throw IllegalStateException("profile_database_unavailable") }
                database = SQLiteDatabase.openDatabase("$ROOT/databases/crypto_user_database", password, null,
                    SQLiteDatabase.OPEN_READONLY or SQLiteDatabase.NO_LOCALIZED_COLLATORS, handler, null)
                require(database.isReadOnly)
                database.rawQuery("SELECT id,nickname,friend_nickname,contact_name,relation FROM user LIMIT 0", null).close()
                database.rawQuery("SELECT id,chat_id,name FROM talk_channel LIMIT 0", null).close()
                return CryptoProfiles(database, password)
            } catch (e: Throwable) {
                database?.close()
                password.fill(0)
                throw e
            }
        }
    }

    fun user(id: String): ProfileData.Name? = db.rawQuery(
        "SELECT nickname,friend_nickname,contact_name,relation FROM user WHERE id=? LIMIT 1", arrayOf(id)
    ).use { c ->
        if (!c.moveToFirst()) null else ProfileData.displayName(c.getString(0),c.getString(1),c.getString(2),c.getInt(3))
    }

    fun channel(user: String, chat: String): ProfileData.Name? = db.rawQuery(
        "SELECT name FROM talk_channel WHERE id=? AND chat_id=? LIMIT 1", arrayOf(user,chat)
    ).use { c -> if (!c.moveToFirst()) null else ProfileData.Name(c.getString(0),"crypto_user.talk_channel") }

    fun channelRoom(chat: String, knownUsers: Set<String>): ProfileData.Name? = db.rawQuery(
        "SELECT id,name FROM talk_channel WHERE chat_id=? LIMIT 2", arrayOf(chat)
    ).use { c ->
        if (c.count != 1 || !c.moveToFirst() || c.getString(0) !in knownUsers) null
        else ProfileData.Name(c.getString(1),"crypto_user.talk_channel")
    }

    override fun close() { try { db.close() } finally { password.fill(0) } }
}
