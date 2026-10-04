# Operations and recovery

For the new installer, passkey admin login, Aurora setup and full encrypted snapshots, see [Set up a personal bridge](onboarding.md). The commands below describe the existing manual deployment path.

[README](../README.md) · [Security](security.md)

The commands below run on a Linux host. On a Mac, the containers run inside Lima, so use `./scripts/lima-compose.sh` instead of `docker compose`.

## Check status

```bash
docker compose --profile dot ps
./scripts/status.sh
docker compose logs --tail 30 iris-collector
```

`collecting_partial` means recent Iris database access and secondary-login approval are valid. It does not mean the system has checked for missing chat history or verified the phone session automatically.

| Symptom | What to check |
| --- | --- |
| Android screen is unavailable | redroid boot status and host binder devices |
| Collection approval is locked | Login precheck and confirmation of both sessions in the admin console |
| Collection stops after an app update | A changed versionCode requires new login confirmation |
| Decryption or JSON error | Iris logs; collection stops rather than skipping invalid rows |
| Database replaced or IDs move backwards | Android restore or database recreation; investigate before registering a new epoch |
| ChatGPT connection fails | dot-ingress, dot-plugin and dot-control status, public HTTPS, the configured passkey hostname and a registered passkey. Ensure the ingress config is readable by UID 10001. Matching approval codes apply only in explicit admin approval mode. See [Connection setup](dot-plugin.md) |
| ADB reports unauthorized | Preserve the original device-state and iris-state keys. Stop Android, rerun adb-init and start Android through Compose to provision those keys; do not disable ADB authentication |

By default, Iris reads up to 50 rows every 3 seconds and continues fetching while a backlog remains. Delivery latency depends on the KakaoTalk and redroid connection state.

## Upgrading to the security update

Existing owners sign in to admin once again with their current passkey. Older browser sessions are rejected after the cookie migration. Registered passkeys and approved MCP connections are retained; the tablet setup and collection controls keep the same workflow. Collector ADB keys are provisioned automatically, so operators using the web UI do not enter another token. Direct ADB/scrcpy clients need an authorized key.

This release also changes the Iris binary and Compose topology. Before updating an existing deployment:

1. Create and verify a full encrypted backup of all seven volumes, configuration and keys. Preserve the old image references and APK hash for rollback.
2. Build/load the server, device and gateway images and update the Compose files together. For published images, use a manifest containing all three image digests.
3. Follow the [explicit Iris component migration](mcp-queries.md#updating-the-iris-component), preserving enrollment and KakaoTalk app data. `./bridge update` deliberately stops if the bundled Iris APK changes; it does not perform this migration automatically. Do not use a fresh bootstrap to upgrade a signed-in tablet.
4. Recreate Android through the updated Compose configuration so `adb-init` provisions the collector keys before `ro.adb.secure=1` takes effect. Preserve `android-data`, `device-state` and `iris-state` together. This step restarts Android; check the tablet and phone sessions afterward.
5. Start the matching application services and `dot-ingress`. Point public HTTPS at its loopback port (18787 by default), and keep the admin gateway private. The ingress config must be readable by UID 10001; do not expose dot-plugin directly.
6. Sign in to admin with the existing passkey, check collection status and query the connected MCP client's profile/status. Check that unauthenticated `/mcp` returns 401 and public `/admin/` returns 404.

The [security report](security.md#security-fixes-2026-10-05) records the tested ARM64 migration and its limits. The automatic installer/release upgrade has not been validated end to end on every host. Redroid's old Android patch level remains a separate risk after this update.

## Stop and restart

```bash
docker compose down
docker compose up -d --no-build
```

`down` preserves volumes. **`down -v` deletes the login state and database.** Do not use it for routine shutdown.

For installations with remote MCP, include `--profile dot` when stopping or starting the complete stack. Public traffic must pass through the separate `dot-ingress` service. Its read-only `docker/Caddyfile.public` mount contains no secrets and must be readable by UID 10001 (normally mode 0644).

`adb-init` runs before Android creation and provisions only the two collector public keys. An authorized collector can still request root ADB. Back up and restore Android, device-state and iris-state together; do not replace keys in a running deployment. The Iris credential file is managed automatically and rotates with enrollment.

Automatic restarts are disabled for redroid to avoid repeated failures. Start it with `docker compose start redroid` when needed. Other long-running services use `unless-stopped`. For automatic recovery on Linux, adjust the paths in `deploy/kakaocollector-supervisor.service.example` and install it. The supervisor limits redroid restarts to three within 30 minutes.

## Storage locations

KakaoTalk Bridge retains existing deployment identifiers for compatibility: `kakaotalk-collector` in Compose project and local image names, the Android package `dev.kakaocollector.bridge`, and the manual Lima path `/srv/kakaotalk-collector`. The new installer's VM path is `/srv/kakaotalk-bridge`; release images use `ghcr.io/rokrokss/kakaotalk-bridge-*`. Keep `COMPOSE_PROJECT_NAME` in your existing `.env` when applying the rename so that the same login and message volumes are used.

| Volume | Contents |
| --- | --- |
| `android-data` | KakaoTalk session and local database; registration app data |
| `collector-data` | Collected messages and server cursors |
| `device-state` | Registration epoch and ADB keys |
| `iris-state` | Iris collector ADB keys |
| `admin-state` | Encrypted optional local password and revocable browser sessions |
| `passkey-state` | Encrypted public credentials, RP/origin configuration and temporary authentication state |
| `dot-state` | OAuth, subscriptions, acknowledged cursors, and webhook queue |

The server prunes observations older than 30 days every hour. Adjust this period with `RETENTION_DAYS`. Retransmission deduplication also applies within this retention window. The Android database, legacy notification quarantine, and backup files are excluded from this cleanup. Container logs are limited to three 10 MB files each.

## Back up the collection database

```bash
./scripts/backup.sh
```

The script creates a consistent copy using SQLite's online backup API and encrypts it with AES-256-GCM. Store `secrets/backup_key` separately from the backup files. Losing the key makes recovery impossible. Configure automatic backup deletion and remote replication yourself.

Stop the API before restoring:

```bash
docker compose stop api
./scripts/restore.sh backups/collector-TIMESTAMP.kcb
docker compose start api
./scripts/status.sh
```

Restore checks the authentication tag, database integrity, and schema. Because `cursor_epoch` changes, API consumers must reset their pagination cursors. Iris resumes from the restored server cursor.

The backup script uses the Docker Engine on the host where it runs. For Lima deployments, run it inside the VM at `/srv/kakaotalk-collector`:

```bash
limactl shell --workdir=/srv/kakaotalk-collector kakaotalk-test sudo ./scripts/backup.sh
```

## Back up Android and MCP state

Prefer the [full snapshot command](onboarding.md#maintain-and-recover), which preserves all seven volumes with their matching configuration and keys. For a manually managed Android snapshot, stop redroid, admin and both device collectors, then save `android-data`, `device-state` and `iris-state` together with the matching collector state and secrets in an encrypted host snapshot. Android contains the Iris bearer; the two collector volumes contain its authorized ADB identities. Do not run the original and restored instances simultaneously with the same account. A manual restoration that requires a new registration epoch uses:

```bash
docker compose --profile setup run --rm bootstrap bootstrap --rotate-epoch
```

This requires secondary-login confirmation again. Iris rereads remaining database rows under the new epoch, which may duplicate previously stored records.

`admin-state`, `dot-state` and `passkey-state` are not included in the collection database backup. Stop admin, dot-plugin and dot-control before copying them, or use SQLite's online backup API. Preserve the matching `secrets/admin_token`, `secrets/mcp_storage_key`, `secrets/mcp_approval_token` and `secrets/mcp_passkey_token`. Copying only a database file while it is running may omit data in the WAL. Full snapshot restoration also clears browser sessions, OAuth grants and callbacks while retaining passkey credentials; a manual file copy does not perform that cleanup.

## Renew certificates

The default TLS certificate lasts 365 days. Include the same gateway IP in the SAN when renewing it, then restart the gateway. The registration app's trusted certificate must also be updated through bootstrap, so schedule time to reconfirm the login sessions. Changing the Bridge signing key prevents app updates.
