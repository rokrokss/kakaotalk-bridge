# Message queries

MCP provides message context as well as text: sender and room names where resolved, whether a message is yours, source send time, and separate server collection time. The same query behavior is available over remote MCP, stdio MCP and the authenticated HTTP `/v2` routes.

| Tool | Use |
| --- | --- |
| `get_recent_messages` | Latest messages by send time, optionally filtered by room, sender or period |
| `search_messages` | Literal body substring plus the same filters |
| `list_conversations` | Distinct rooms, names, retained message counts and latest message times; `q` filters room names |
| `get_conversation_context` | Earlier/later collected messages around a returned `message_id`, in the same room |
| `get_collector_status` | Collection health, coverage and aggregate name-resolution state |

Recent and search accept `limit` (1–100), `conversation_ref`, `sender_ref`, `sender_name`, `since`, `until`, `include_mine` and `cursor`. Name matching is literal substring matching over the displayed current or historical names. Check `name_status`; similar names can match different people, so use returned refs to disambiguate. Refs are identifiers, never display names.

`since` is inclusive and `until` exclusive. Both require ISO 8601 timestamps with a UTC offset. For October 4 in Abu Dhabi, use `2026-10-04T00:00:00+04:00` through `2026-10-05T00:00:00+04:00`. Filters apply before the limit, including a room's latest N messages.

Results include `sender`, `conversation`, `is_mine`, `sent_at`, `collected_at`, `body`, `message_type`, `source` and `truncated`. Use `sent_at` for the user's message time; `collected_at` is when the collector stored it. Unknown send times remain null, sort last in recent results, and do not match time filters. Message types are raw KakaoTalk codes; original media is not downloaded.

Pass `next_cursor` back as `cursor` with the same filters to retrieve older results. A signed cursor fixes the message snapshot and sort boundary. A changed filter, database restore or retention pruning invalidates the cursor. Queries filtered by `sender_name`, or conversation-name `q`, also expire when display metadata or nickname evidence changes; an unchanged metadata refresh does not expire them. Start again without a cursor after `invalid_query_or_expired_cursor`. Other queries retain their message snapshot while displayed names can refresh between pages.

Context accepts a returned `message_id`, `before` (0–30) and `after` (0–30), defaulting to five on each side. It returns chronological messages, including the target, with flags for additional context. It never opens a chat or changes read receipts.

## Names

Names are resolved separately from immutable message ingestion. This allows existing stored messages to acquire names without reinserting messages or emitting duplicate events. Open-chat nicknames are scoped by both link/room and user, so one room's nickname is never reused in another room accidentally.

The resolver reads local databases in read-only mode. Open chats use exact `KakaoTalk2.db` member and link records. The current profile adapter reads `crypto_user_database.user` by the message sender ID; older versions can use the optional `friends` table. Member-derived room names require every included member to resolve. Own messages can use the explicit `Me` label; self-chat can use `Saved messages`.

For modern ordinary profiles, display-name precedence follows the app: nonblank `friend_nickname`, then `contact_name`, then `nickname`. Deactivated profiles (`relation=9`) use `nickname`. A contact name is used only from the exact observed sender's KakaoTalk user record and is identified as `crypto_user.contact_name`; the collector does not enumerate the phone address book or join people by phone number. PlusChat names require both a matching channel ID and chat ID. Room names additionally require a unique channel row whose ID appears among the room's members or locally stored senders.

Each name includes `name_status`, `name_reason`, `name_source` and `updated_at`. Unattempted lookups are `pending`; absent rows are `not_found`; schema/database/decryption errors are `unavailable`. Ciphertext is never exposed as a name. Missing names are diagnostic conditions rather than invented labels.

For open rooms (`OM`/`OD`), a non-self sender without a resolved profile can use a nickname from a retained type-0 system message: feed 2 (`member`) or feed 4 (`members`). Matching requires the same device, registration epoch, conversation and exact integer user ID. Ordinary message text is never treated as nickname evidence. The newest source event time wins, with collector message ID breaking ties; late imports of older events do not overwrite newer evidence. Truncated events, unknown event times, unsupported or malformed shapes and ambiguous names are ignored. Parsing is bounded to 16,384 characters, 100 members and 512 characters per name.

These senders have `name_status="historical"`, `name_reason="historical_name_current_unverified"` and `name_source="open_chat_feed.leave"` or `"open_chat_feed.join"`. `name_observed_at` is the source time of the event recording that nickname; `name_evidence_message_id` identifies the retained event for context lookup. Both fields are null for current profiles. `updated_at` continues to mean the current-profile lookup time, not the event time. Label historical names accordingly: they are neither verified current names nor proof of what name was in use when each returned message was sent.

Current resolved profiles always take precedence. Historical evidence does not suppress profile refreshes. Retention removes evidence with its source event; a remaining older event can then supply the fallback, otherwise the name becomes unresolved. The API backfills retained events at startup and indexes new ones during ingestion, without replaying messages or changing event identities. Status aggregates distinguish `historical` from `resolved`.

The collector processes up to 50 observed room/sender pairs every ten seconds, prioritizing recent messages that have not been looked up. Targets travel in a bounded JSON POST body to avoid HTTP request-line limits. Resolved names become eligible for refresh after one hour, unresolved names after one minute. A metadata failure does not discard or stop collected message bodies. `/v1/status.identity_metadata` reports aggregate resolution counts without names.

KakaoTalk 26.8.2 stores ordinary profiles in a SQLCipher database instead of the old `friends` table. The profile adapter in Iris v4 derives its local database passphrase from existing on-device preferences; it never creates or changes those preferences and never sends the key to the API, MCP, logs or disk. The SQLCipher dependency is pinned by SHA-256. The reader supplies a non-destructive corruption handler and never runs migrations or a writable database helper. Missing keys, incompatible schemas or unavailable records produce an explicit unresolved state unless supported historical open-chat evidence is available. See [Iris](iris.md) for compatibility and verification limits.

## HTTP and compatibility

- `GET /v2/messages`: recent/search filters above; add `q` for body search.
- `GET /v2/conversations`: `q`, `limit`, `cursor`.
- `GET /v2/context`: `message_id`, `before`, `after`.

All require the existing API read credential. OAuth MCP clients continue to use the `kakao.read` scope. Remote tools publish structured output schemas.

The MCP query tools now use opaque `cursor`, replacing their old numeric `after`/`cursor_epoch` arguments. Refresh the client's tool catalog if it still sends the old arguments. HTTP `/v1/messages`, `/v1/search`, `/v1/conversations` and event tools retain the numeric ingestion cursor. Pending event pages retain their existing row shape; pass a pending row's `id` as `message_id` to `get_conversation_context` for named context. Never pass query cursors to `acknowledge_messages`. Automatic event subscriptions remain disabled.

## Updating the Iris component

The historical-name fallback needs only the API and MCP server update; it uses already-collected records and does not require replacing Iris, reinstalling KakaoTalk or logging in again. Back up the collector database before updating. The component migration below applies when upgrading the Android profile reader itself.

Modern encrypted profiles were added in Iris v3; the current build is v4 and also authenticates `/collector/metadata` and `/collector/rows`. Upgrade both the Android component and its Python collector to the current build. A server-only update cannot supply names or add this caller authentication. Keep the existing enrollment and Android app data. Do not run a fresh `bootstrap` to apply this update; the explicit `bootstrap iris-upgrade` subcommand below preserves enrollment.

Back up the database and configuration, build/load both images, and stop `iris-collector` before replacing its component. With `DEVICE_IMAGE` set to the new image, run the explicit component migration using the exact previous APK SHA-256:

```bash
docker compose stop iris-collector
docker compose --profile setup run --rm --no-deps bootstrap iris-upgrade \
  --expected-iris-sha256 <previous-iris-apk-sha256>
```

The command verifies the current APK and uploaded replacement, preserves an Android-side copy named `kakaocollector-iris.apk.backup-<sha256>`, and replaces only the root `app_process` component. It checks existing enrollment before and after upload, without reinstalling KakaoTalk or changing login confirmation. A start failure restores the old APK; select the previous image and restart its collector to recover.

Start the new API, remote MCP and `iris-collector` images, then verify `/v2/messages` and name-resolution status. Follow the [security upgrade notes](operations.md#upgrading-to-the-security-update) for authenticated ADB and the public ingress. Ordinary `./bridge update` still refuses an Iris binary change so this explicit migration cannot happen accidentally.
