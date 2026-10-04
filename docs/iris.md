# Iris collection implementation

[README](../README.md) · [Operations and recovery](operations.md)

## Components and assumptions

redroid on the Linux server acts as a secondary tablet, without a separate physical tablet. The existing phone remains the primary device. Iris runs inside redroid as a root `app_process`, while the Python `iris-collector` runs in a separate Docker container. This setup does not use Termux or desktop KakaoTalk.

redroid's tablet size and model properties do not guarantee secondary login. On the actual login screen of the official KakaoTalk APK, verify that “Use with other devices” (“다른 기기와 함께 사용” in the Korean UI) is selected. After signing in, the operator must confirm that both the phone and redroid sessions remain active. The code does not prevent phone sign-out or monitor the phone session. Secondary login and collection of new messages have been verified in Lima on Apple Silicon; the user manually confirmed phone session continuity.

## Running the collector

The [web admin console](web-ui.md) is the primary interface for screen control, installation, and login confirmation. The CLI commands below are an alternative to the corresponding web actions; do not use them concurrently.

After preparing the kernel, secrets, and official KakaoTalk APK as described in [Linux installation](install.md):

```bash
docker compose build api device-agent gateway
docker compose up -d
docker compose --profile setup run --rm bootstrap
```

Open the redroid screen in admin and select the secondary-device option on the Korean login screen. A separate scrcpy client requires an authorized ADB identity; forwarding the port alone does not grant access. Before pressing the login button:

```bash
docker compose --profile setup run --rm bootstrap login-check
```

After the check passes, sign in as a secondary device and confirm that the existing phone session remains active. Within 30 minutes:

```bash
docker compose --profile setup run --rm bootstrap confirm-secondary \
  --phone-session-active --tablet-session-active
./scripts/status.sh
docker compose logs --tail 30 iris-collector
```

`--tablet-session-active` confirms the redroid session, not a separate tablet. Bridge does not need notification access. Migrating an existing registration from the legacy notification version also requires running bootstrap again with the new image. This resets confirmation and requires operator participation. Do not guess an unverified secondary-login flow or proceed with a primary-device transfer.

## Iris build and runtime boundaries

- Upstream: https://github.com/dolidolih/Iris, commit `ee1dc978ec465df11642596e40f74caff497301d`.
- The archive SHA-256 `1b194b137b0912ef360a4a0b511c6ed5169aaaf0da85c1de1cf59b325bebfcd0` is checked during the build.
- This modified build adds `iris/CollectorMain.kt`. It does not run upstream `Main`; it uses only database reads and Iris decryption. The database is opened with Android SQLite `OPEN_READONLY`.
- It does not start upstream message sending, notification polling, file deletion, the dashboard, `/query`, `/reply`, or `/aot`. It exposes `/collector/rows` and `/collector/metadata` for bounded fixed SELECT queries, and `/collector/health` for build verification.
- It binds only to Android `127.0.0.1:3000`, reached through a loopback ADB forward inside the collector. Compose does not publish port 3000 on the host. Hosts and containers with root ADB access are within the trust boundary.
- Iris v4 authenticates data requests with a random per-enrollment bearer before accessing databases. Its credential file is root-owned, mode 0600, inside `/data/kakaocollector-iris` (0700). A nonce/HMAC health challenge verifies the expected listener before Python sends the bearer. Credentials are not included in logs or process arguments.
- `adb-init` provisions the existing device and Iris collector public keys before Android starts. `ro.adb.secure=1` rejects unregistered ADB clients; authenticated collectors can still use the root access required by Iris. Private keys remain in their state volumes. Preserve these volumes with Android data when backing up or restoring.
- Every request checks registration mode, secondary-login confirmation, Android fingerprint, and Kakao versionCode. The Python side also checks tablet settings and registration before and after page queries and before sending each row.
- The APK is a build artifact for `app_process`, not a signed package for app installation. Bootstrap deploys it with read-only file permissions, and the collector compares its SHA-256 with the APK in the image at startup.
- GPL/MIT notices and corresponding source are included in `iris/NOTICE.md`, `/opt/iris-source.tar.gz`, `/opt/iris-overlay/`, and `/opt/iris-build.Dockerfile` in the image. Distribute the source and notices with the build.
- Netty modules are aligned to `4.1.138.Final`. `/opt/iris-dependencies.txt` contains the resolved release dependency graph. See [security fixes and remaining Android patch debt](security.md#security-fixes-2026-10-05).

## Storage and recovery

The initial cursor is 0. The collector reads up to 50 rows at a time from those currently present in redroid's KakaoTalk database, including synchronization rows such as `SYNCMSG`. It cannot access the phone's entire history or all history on Kakao's servers.

`_id`, `chat_id`, and `user_id` are passed as strings. Event IDs are derived from the Iris-specific registration epoch, database identity, and log ID. Different log IDs represent different messages even when the body matches. Retransmissions that differ only in observation time receive a duplicate acknowledgment. Immutable rows retain conversation and sender IDs. A separate metadata refresh resolves supported local display names without changing row identity or replay digests; see [Message queries](mcp-queries.md#names).

The collector waits for a commit acknowledgment for each row. The server stores the row and latest cursor in the same SQLite transaction. After a lost response or collector restart, it queries the server cursor again rather than trusting a local cursor file. It does not skip invalid rows and save a later cursor. The app database serves as the source queue, so rows deleted from the app during a server outage cannot be recovered.

Server retention cleanup preserves the Iris cursor even when it deletes messages. Encrypted database backups include the cursor. After a server restore, collection resumes from the restored cursor. Android database replacement (a changed file device/inode) or a decrease in the maximum ID stops collection; a new database is not approved automatically. Changes that reuse the same IDs in the same file, or edits and deletions of existing rows, cannot be fully detected.

The initial collection scope, deleted rows, and delayed synchronization mean `coverage.complete=false` at all times. A connected heartbeat indicates Iris database access, not a connection to Kakao's servers or a valid phone session. Legacy notification messages use `source=notification`; new database messages use `source=iris_db`.

## Current limits and operational validation

Message bodies are limited to 16,384 UTF-16 code units, with truncation flagged. Collection currently includes the row body, message type, IDs, timestamps, origin, and isMine. Display names are resolved separately. Iris v4 includes read-only SQLCipher access to KakaoTalk 26.8.2's `crypto_user_database`: exact sender IDs select ordinary profiles and exact channel/chat ID pairs select PlusChat names. The passphrase is derived inside Android from existing preferences, never created, written or exported. When an open-chat profile is absent, the API can use a nickname from a retained join/leave event in the same room, explicitly marked historical with the event time. Names without either source remain unresolved. Original attachments and edit/deletion synchronization are not implemented. JSON or decryption errors stop the page; ciphertext is not stored as a valid message body.

Check the following in new environments; these also define the remaining validation scope:

1. Kernel/binder, KakaoTalk APK ABI, and root database access compatibility.
2. Secondary-login option and continuity of the existing phone session.
3. Database reception and decryption for regular chats, muted chats, screen-off operation, own messages, and synchronization messages.
4. Read status before and after collection, app/container restarts, and resumed collection after network loss.
5. Continuous reception and disk usage over 24–72 hours.

Successful local API tests and APK builds do not substitute for these checks.
