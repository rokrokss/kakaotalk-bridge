# Iris collection implementation

[README](../README.md) · [Operations and recovery](operations.md)

## Components and assumptions

redroid on the Linux server acts as a secondary tablet, without a separate physical tablet. The existing phone remains the primary device. Iris runs inside redroid as a root `app_process`, while the Python `iris-collector` runs in a separate Docker container. This setup does not use Termux or desktop KakaoTalk.

redroid's tablet size and model properties do not guarantee secondary login. On the actual login screen of the official KakaoTalk APK, verify that “Use with other devices” (“다른 기기와 함께 사용” in the Korean UI) is selected. After signing in, the operator must confirm that both the phone and redroid sessions remain active. The code does not prevent phone sign-out or monitor the phone session. Secondary login and collection of new messages have been verified in Lima on Apple Silicon; the user manually confirmed phone session continuity.

## Running the collector

The [web admin console](web-ui.md) is the primary interface for screen control, installation, and login confirmation. The CLI/scrcpy flow below is an alternative; do not use it concurrently with web operations.

After preparing the kernel, secrets, and official KakaoTalk APK as described in [Linux installation](install.md):

```bash
docker compose build api device-agent
docker compose up -d
docker compose --profile setup run --rm bootstrap
```

Open the redroid screen through scrcpy/an SSH tunnel and select the secondary-device option on the Korean login screen. Before pressing the login button:

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
- It does not start upstream message sending, notification polling, file deletion, the dashboard, `/query`, `/reply`, or `/aot`. It exposes only `/collector/rows` for fixed SELECT queries and `/collector/health` for build verification.
- It binds only to Android `127.0.0.1:3000`, reached through a loopback ADB forward inside the collector. Compose does not publish port 3000 on the host. Hosts and containers with root ADB access are within the trust boundary.
- Every request checks registration mode, secondary-login confirmation, Android fingerprint, and Kakao versionCode. The Python side also checks tablet settings and registration before and after page queries and before sending each row.
- The APK is a build artifact for `app_process`, not a signed package for app installation. Bootstrap deploys it with read-only file permissions, and the collector compares its SHA-256 with the APK in the image at startup.
- GPL/MIT notices and corresponding source are included in `iris/NOTICE.md`, `/opt/iris-source.tar.gz`, `/opt/iris-overlay/`, and `/opt/iris-build.Dockerfile` in the image. Distribute the source and notices with the build.

## Storage and recovery

The initial cursor is 0. The collector reads up to 50 rows at a time from those currently present in redroid's KakaoTalk database, including synchronization rows such as `SYNCMSG`. It cannot access the phone's entire history or all history on Kakao's servers.

`_id`, `chat_id`, and `user_id` are passed as strings. Event IDs are derived from the Iris-specific registration epoch, database identity, and log ID. Different log IDs represent different messages even when the body matches. Retransmissions that differ only in observation time receive a duplicate acknowledgment. Conversation and sender IDs are provided instead of display names.

The collector waits for a commit acknowledgment for each row. The server stores the row and latest cursor in the same SQLite transaction. After a lost response or collector restart, it queries the server cursor again rather than trusting a local cursor file. It does not skip invalid rows and save a later cursor. The app database serves as the source queue, so rows deleted from the app during a server outage cannot be recovered.

Server retention cleanup preserves the Iris cursor even when it deletes messages. Encrypted database backups include the cursor. After a server restore, collection resumes from the restored cursor. Android database replacement (a changed file device/inode) or a decrease in the maximum ID stops collection; a new database is not approved automatically. Changes that reuse the same IDs in the same file, or edits and deletions of existing rows, cannot be fully detected.

The initial collection scope, deleted rows, and delayed synchronization mean `coverage.complete=false` at all times. A connected heartbeat indicates Iris database access, not a connection to Kakao's servers or a valid phone session. Legacy notification messages use `source=notification`; new database messages use `source=iris_db`.

## Current limits and operational validation

Message bodies are limited to 16,384 UTF-16 code units, with truncation flagged. Collection currently includes the row body, message type, IDs, timestamps, origin, and isMine. Original attachments, display-name lookup, and edit/deletion synchronization are not implemented. JSON or decryption errors stop the page; ciphertext is not stored as a valid message body.

Check the following in new environments; these also define the remaining validation scope:

1. Kernel/binder, KakaoTalk APK ABI, and root database access compatibility.
2. Secondary-login option and continuity of the existing phone session.
3. Database reception and decryption for regular chats, muted chats, screen-off operation, own messages, and synchronization messages.
4. Read status before and after collection, app/container restarts, and resumed collection after network loss.
5. Continuous reception and disk usage over 24–72 hours.

Successful local API tests and APK builds do not substitute for these checks.
