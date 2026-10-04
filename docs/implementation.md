# Validation scope

[Development and test commands](development.md) · [Current architecture](design.md)

## Verified with a real account

On 2026-10-04, using Lima/Ubuntu 24.04 arm64 on an Apple Silicon Mac:

- redroid boot with Android 14, SM-T970 tablet configuration, and 1200 × 1920 resolution at density 240.
- Screen viewing, control, and Korean text input through the web admin console.
- KakaoTalk secondary-device option check (“다른 기기와 함께 사용”, meaning “Use with other devices”) and secondary login.
- Phone session continuity, manually confirmed by the user on the phone; this was not an automated server check.
- Iris database row storage and collection of new messages sent to self after approval.
- State volume persistence across container and VM restarts.
- Public HTTPS OAuth flow and successful connection of `KakaoTalk Bridge` in ChatGPT.

## Automated checks

Python tests use synthetic data to cover authentication, CSRF, Origin, login approval conditions, database deduplication, cursors, restores, MCP queries, and event retries, revocation, and expiry. Docker smoke tests cover the API, gateway, stdio MCP, SQLite, and encrypted backups.

Image builds and API startup have been verified on amd64. This does not establish redroid or KakaoTalk compatibility on an amd64 host. Reproduction commands are in [Development](development.md).

## MCP message queries (2026-10-04)

The [query API](mcp-queries.md) now separates send time from collection time, returns structured sender/room metadata, supports sender/room/date filters and stable pagination, lists distinct conversations and retrieves surrounding conversation context. The remote catalog contains eight tools. Numeric event cursors and pending/ack behavior remain unchanged.

`uv run pytest -q` reported **187 passed** with the existing Starlette TestClient warning. `uv run ruff check .` reported **All checks passed!**, and `git diff --check` passed. Tests cover timestamp ordering, literal search, filters, signed cursors, late history, room-scoped names, context, metadata refresh, retention, restore and real API-to-MCP output-schema validation. Both arm64 images built successfully.

The real Lima deployment was backed up with authenticated encryption before replacing the Iris component and query services. The Iris migration verified both APK hashes and preserved its previous binary. Before/after container comparisons confirmed that redroid, gateway, device-agent and the passkey authority were not recreated. The signed-in KakaoTalk package and enrollment were not replaced.

Production checks passed for latest-first ordering, pagination without overlapping rows, room and resolved-sender-name filters, 22 distinct conversations and same-room context. Calls through the installed connector succeeded for recent messages, profile and collector status; a recent-message response included resolved sender and room names. The collector remained `collecting_partial` with Iris connected. After the first metadata pass, 390 observed room/sender pairs comprised 139 resolved sender labels (129 open-member records and 10 self labels), 236 missing local profile records and 15 unavailable legacy friend-table lookups. These are pair counts, not distinct people. No metadata transport errors appeared in 32 polls after the corrected deployment.

Bulk metadata initially exceeded the server's GET request-line limit. It now uses a bounded POST JSON body. At this checkpoint, ordinary sender names were still unresolved because the installed KakaoTalk version had no legacy `friends` table. The encrypted-profile integration below resolves that limitation. No KakaoTalk messages were sent or chats opened for these checks. The installed client may need to refresh its tool catalog to discover the new context tool and query arguments. These agent-invoked checks do not establish execution inside the user's Dot conversation.

## Encrypted profile names (2026-10-04)

The installed KakaoTalk 26.8.2 APK (versionCode 29260820) matched the local inspection APK by SHA-256. Its database schema and display-name code identified `crypto_user_database.user`, the local key-preference format, the app's display-name precedence and the distinct `talk_channel` ID/chat-ID fields. No APK or decompiled application source is distributed in this repository.

Iris v3 adds read-only SQLCipher access with a pinned library, schema checks and non-destructive corruption handling. It uses exact observed sender IDs, preserves open-chat link/user scoping and keeps database key material within Android memory. The preference and database files are not created or migrated. The displayed name may come from a user-defined nickname, an existing KakaoTalk contact-name field, or the profile nickname; its source is returned explicitly. Phone address-book enumeration and phone-number joins are not used.

Validation results:

- `:app:testReleaseUnitTest :app:assembleRelease`: **BUILD SUCCESSFUL**, **10 profile tests, 0 failures, 0 errors**. Tests cover positive/negative PBKDF2 vectors, fallback keys, malformed preferences, display-name precedence and deactivated profiles.
- `uv run pytest -q`: **187 passed**, with the existing Starlette TestClient warning. `uv run ruff check .`: **All checks passed!**; `git diff --check` passed.
- A separate Android probe opened the real encrypted DB with `read_only=true`. All observed non-self ordinary pairs matched: DirectChat **3/3**, MultiChat **9/9**, PlusChat **3/3**. All three channel identities also appeared among their respective room members. Only aggregate counts were printed.
- After deployment and metadata refresh, the API resolved all **15/15** ordinary/channel pairs: 8 user-defined nicknames, 4 profile nicknames and 3 channel names. The contact-name fallback has unit/static-code coverage but was not selected by these production rows.
- An actual call through the installed MCP connector returned **10/10 recent sender names and 10/10 room names**, including 3 rows resolved by the new adapter. The retained query suite passed ordering, pagination, sender/room filters and context checks over **22 distinct rooms**.

An encrypted backup preceded the component migration. The previous Iris APK was retained, and deployed source/license hashes matched the checkout. Only admin and iris-collector containers were recreated; redroid, device-agent, API, remote MCP, gateway and passkey authority IDs/start times remained unchanged. Collection continued with Iris connected. No test message was sent or chat opened.

The current snapshot still contains 236 unresolved open-chat room/sender pairs with no matching local member record. This is separate from the now-resolved encrypted ordinary-profile format. Compatibility with other KakaoTalk versions and schema/key changes remains unverified; unavailable data is reported instead of guessed.

## Open-chat missing names: follow-up investigation (2026-10-04)

This was a read-only investigation, with no collector changes or deployment. Among 365 observed non-self open-chat room/sender pairs, 236 pairs (236 user IDs across seven rooms) had no matching local open-member record. None matched another link's member record, `open_profile`, or the link owner. None appeared in the stored member/active-member arrays; these arrays can be partial, so this does not prove that all 236 people left their rooms.

A second path exists in already-collected system messages. The installed APK defines feed type 2 as LEAVE with `member.userId`/`member.nickName`, and type 4 as OPENLINK_JOIN with `members[].userId`/`nickName`. Exact same-room/user matching found historical names for **26 of the 236 pairs** in 27 observations (21 leave, 6 join). One pair has two different historical nicknames. These names are evidence from the event time and must not be presented as current profiles. Other observed feed types 14, 25 and 26 did not provide a participant-name path.

The app's code also contains an on-demand `member(chatId, memberIds)` request, whose response includes nicknames and updates the local profile cache by link and user. The collector does not invoke that authenticated app-session protocol. No such request was executed in this investigation, so remote recoverability for the remaining 210 pairs is unverified. A room snapshot may supply parallel display ID/name arrays, but the inspected local room records contained only display IDs, without corresponding name arrays.

Reproduction commands and observed output (private investigation scripts under ignored `artifacts/`, no personal values printed):

```text
python3 artifacts/open-member-research/aggregate.py
  total_pairs=365, missing_pairs=236, affected_rooms=7
  another_link_same_user=0, exact_open_profile=0
limactl shell --workdir=/ kakaotalk-test sudo docker exec -i kakaotalk-collector-api-1 python - < artifacts/open-member-research/system_names.py
  missing_pairs=236, matched_missing_pairs=26, multiple_historical_names=1
JAVA_HOME=/opt/homebrew/opt/openjdk@21 bash artifacts/name-storage/jadx/bin/jadx --no-inline-anonymous -d artifacts/open-member-research/agent/feedtype artifacts/name-storage/classes9.dex
  Re-decompiled FeedType constructors expose LEAVE=2 and OPENLINK_JOIN=4.
```

Static evidence is in the local inspection outputs: `feedtype/sources/defpackage/z3r.java:225` (leave), `:397` (join), `jp80.java:145` (join member payload), and the previous decompilation's `defpackage/uf9.java:299` (local lookup/fallback and requested refresh), `nn9.java:3752` (member response), `ll9.java:1620` (paired snapshot names). No decompiled application source is distributed. Collection remained `collecting_partial` with Iris connected after the checks.

The follow-up implementation is recorded below.

## Historical open-chat nickname fallback (2026-10-04)

Implemented and deployed to the API/MCP services. Resolved profiles retain priority. When a non-self sender in an `OM`/`OD` room has no resolved profile, a separate index selects the last retained join/leave nickname for that exact device, epoch, conversation and user. Source event time determines recency; message ID breaks ties. Malformed, ambiguous, truncated, unsupported and undated evidence is skipped. Evidence expires with its source message, and current-profile refresh continues independently.

The MCP/HTTP sender view distinguishes `historical` from `resolved`, exposes `name_observed_at` and `name_evidence_message_id`, and keeps `updated_at` as the profile lookup time. Remote and stdio instructions explain the distinction. Name search and status counts use the same fallback. Name-filtered pagination now expires when display metadata or evidence changes; unchanged metadata refreshes preserve the cursor. Other message cursors and legacy event payloads are unchanged.

Validation commands and actual results:

```text
uv run pytest -q
  220 passed, 1 warning in 9.12s
uv run ruff check .
  All checks passed!
git diff --check
  exit 0, no output
limactl shell --workdir=/ kakaotalk-test sudo docker exec -i kakaotalk-collector-api-1 python - < artifacts/historical-names-check/verify_snapshot.py
  missing_pairs=238, historical_pairs=28, still_missing_pairs=210
  current_profiles_unchanged=true, observations_unchanged=true, event_progress_unchanged=true
```

The live-data check opened the production DB read-only, copied it into memory and loaded the new implementation only for that process. New data since the earlier investigation accounts for the difference from 236/26 to 238/28. The script printed counts and booleans only, validated historical responses against the new schema, and wrote nothing to the live DB. These are pre-deployment results, not evidence of the running connector using the change.

Tests cover current-profile precedence; exact room/user/device/epoch scope; source-time ordering, ties and late imports; bounded parsing and large IDs; schema-valid remote MCP output; name search/status; cursor invalidation; retained-data backfill/restart; evidence removal; and unchanged ingestion progress. The existing Starlette TestClient deprecation warning remains.

### Production deployment verification

Deployed `kakaotalk-collector/server:historical-names-20261004` on the existing Lima host. Image build succeeded, and all application source hashes matched the tested checkout. Comparison with the previously running image found changes only in the six API/MCP files for this feature. Only `api` and `dot-plugin` were recreated; redroid, Iris collector, admin, device-agent, gateway and passkey authority retained their container IDs and start times. Passkey configuration/credentials, admin sessions, MCP grants and the profile identity matched the pre-deployment audit.

An authenticated encrypted backup of the four application databases, secrets and deployment configuration is stored on that host at `/srv/kakaotalk-collector/backups/historical-names-20261004/state.bin` with mode `0600`. The first backup attempt could not access SQLite WAL files through read-only volume mounts and stopped before changing services. The completed backup used SQLite `mode=ro` connections on writable mounts for WAL shared-memory bookkeeping; each database passed `integrity_check`, and the saved encrypted archive was decrypted in memory to verify authentication and contents.

```text
limactl shell --workdir=/ kakaotalk-test sudo python3 /tmp/historical-names-rollout/deploy.py
  PASS: encrypted four-database/configuration backup authenticated
  PASS: built application source hashes match tested checkout
  PASS: API and MCP healthy; other six containers unchanged
  PASS: passkey credentials, admin sessions, MCP grants and profile preserved
limactl shell --workdir=/ kakaotalk-test sudo docker exec -i kakaotalk-collector-api-1 python - < artifacts/historical-names-rollout/verify.py
  historical_pairs=28
  historical_context_and_provenance=true, historical_name_search=true
  current_profile_precedence=true, recent_schema_and_pagination=true
  collector_state=collecting_partial, iris_connected=true
Installed connector: get_recent_messages(limit=100)
  100 rows: 95 resolved current names, 5 historical names
  Historical rows all included name_observed_at and name_evidence_message_id.
Public HTTPS checks
  OAuth resource discovery=200, /admin/=404, unauthenticated POST /mcp=401
```

The deployed data had 238 open-chat pairs without current profiles: 28 used historical evidence and 210 remained unnamed. The connector check used the existing authenticated connection, without relinking, subscribing, acknowledging events or sending messages. It verifies this agent's MCP call; it does not claim a separate user-invoked Dot conversation query. Only aggregate results were printed.

## Passkey authentication (2026-10-04)

The owner completed real passkey registration and reported completing the client connection. Calling the installed connector from the agent returned `KakaoTalk Bridge` from `get_profile` and `collecting_partial` with an active Iris listener from `get_collector_status`. These calls verify connector access; they do not establish message retrieval or event execution in the user's Dot conversation.

Native Chromium WebAuthn tests use a virtual CTAP2 credential for registration, login, remembered sessions, reload, the same credential on both origins, explicit MCP consent, cancellation, PKCE, refresh rotation and tool discovery. Python tests use real ES256 signatures to check challenge, browser, origin, RP, user handle, user verification, expiry, replay and counter rollback. Additional coverage checks recovery, last-key protection, private authority isolation and migration preserving passkey sessions/grants.

Kakao OAuth code and UI have been removed. Passkeys are the default; setup and recovery are documented in [Passkeys](passkeys.md).

After removal, `uv run pytest -q` reported **172 passed** with the existing Starlette TestClient deprecation warning; `uv run ruff check .`, JavaScript syntax checks, Compose configuration, local documentation links and `git diff --check` passed. `node tests/passkey_browser.cjs` passed the native WebAuthn flow described above. Removed provider tests account for the smaller suite compared with the earlier trial.

The arm64 device and server images were built and their deployed source hashes checked. An authenticated encrypted backup includes the current admin, OAuth and passkey databases plus configuration and secrets. Only admin, dot-plugin and dot-control were recreated. Before/after comparisons confirmed unchanged passkey configuration, credential identities, passkey admin sessions, MCP grants and profile identity; retired provider configuration was removed. The five collector/device container IDs and start times remained unchanged.

Production reports `mode=passkey`, `configured=true`, `owner_registered=true`. Public OAuth discovery returns 200; public admin/private-authority paths and removed provider routes return 404. Post-deployment calls through the installed connector again succeeded for `get_profile` and `get_collector_status`, with an active Iris listener, no warnings, no queued rows and no event subscriptions. This is evidence of agent-invoked connector access, not a completed query or event run in the user's Dot conversation.

## Earlier password/pairing onboarding checks (2026-10-04)

The new owner login, setup guide, private connection approval, installer and snapshot commands were checked separately from the real-account deployment:

- Python regression tests cover one-use/expired pairing, password authentication, restart persistence, CSRF, session revocation, private approval, PKCE, setup preservation, signature rejection and authenticated snapshot restoration.
- Both server and device images built successfully on Docker Desktop arm64. Bridge release lint and APK signature verification passed during the device build.
- A separate Docker Compose project with synthetic credentials passed HTTPS pairing, an admin restart, private approval, OAuth token exchange, MCP access, grant revocation and browser revocation. Public control paths returned 404.
- A full snapshot of the synthetic Docker volumes was encrypted and restored into new volumes; existing volumes were retained. The test also exposed and fixed unsupported xattrs on Docker Desktop host binds.
- The device image verified the publisher certificate of the previously downloaded official KakaoTalk APK.
- The setup guide and access-management layout were checked in a browser using an HTTP mock preview. The real HTTPS browser flow was not exercised for these changes because the test CA is not trusted by that browser; backend HTTPS tests explicitly trusted only the test certificate.

Before committing these changes, `uv run pytest -q` reported **152 passed** with one Starlette TestClient deprecation warning, and `uv run ruff check .` reported **All checks passed!** Both JavaScript entry points passed `node --check`; `docker compose --profile dot config --quiet` and `git diff --check` also passed. The suite includes the canonical release image namespace and reuse of the saved private Tailscale URL on Linux.

These checks did not update the signed-in redroid instance or repeat account login. Fresh Lima installation through the new CLI, the newly scripted Korean-locale preparation, both architectures of the release workflow, Tailscale route setup and published release downloads still require integration validation. The earlier manual Aurora/Korean-secondary-option check is separate evidence, not a complete installer test. Tailscale identity sign-in remains future work; passkey verification is recorded below.

## Security remediation deployment (2026-10-05)

The [security report](security.md#security-fixes-2026-10-05) records findings, changes, scan scope and the remaining Android patch risk. Deployed Iris v4 caller authentication, authenticated ADB, separate public/private networks, cookie-filtering ingress, admin cookie migration, stateless pending OAuth registration, updated runtime libraries and container limits.

`uv run pytest -q` returned **227 passed, 1 warning**; `uv run ruff check .` and `git diff --check` passed. The device build passed Kotlin tests with Netty `4.1.138.Final`. The ingress smoke test passed 15 cookie cases, 5 private-path denials and a published-loopback-port check. The native Chromium virtual-authenticator test passed registration, admin login, scoped session persistence, explicit OAuth consent, PKCE, refresh, MCP discovery and replay rejection. These tests use synthetic identities.

The real ARM64 deployment now runs server/device `security-20261005-r2` and gateway `security-20261005`. The full pre-migration encrypted snapshot was authenticated. Final source hashes, APK hashes, passkey identities, MCP grants and profile identity were checked. A temporary ingress 502 was corrected by fixing file permissions and giving the isolated ingress a separate edge network for Docker port publishing; health checks were added. Final public MCP returned 401 without OAuth; public admin routes returned 404. The already connected client's **get_profile** and **get_collector_status** then succeeded, reporting `collecting_partial`, Iris connected and no warnings. No message body was queried or sent during these checks.

Redroid restarted once to enforce ADB authentication, with its existing data volume. The final dependency/ingress rollout kept that Android container running. Registered passkeys and MCP connections remain, while the owner must log back into admin once after the cookie migration. This does not automatically verify the phone session. The old Android OS security patch level remains open; moving to an unverified major image was not included in this rollout.

## Not yet verified

Compatibility with other KakaoTalk versions and hosts, completeness of conversation history, end-to-end comparison of read status before and after collection, and 24–72 hours of continuous reception require further validation. Actual Dot event execution has not been verified, and automatic subscription is not a requirement.

Details of the initial notification-based MVP and troubleshooting history remain in Git. Refer to [Iris](iris.md), [Admin console](web-ui.md), and [MCP](dot-plugin.md) for current behavior.
