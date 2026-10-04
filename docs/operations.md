# Operations and recovery

For the new installer, browser pairing, Aurora setup and full encrypted snapshots, see [Set up a personal bridge](onboarding.md). The commands below describe the existing manual deployment path.

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
| ChatGPT connection fails | dot-plugin and dot-control status, public HTTPS, and the matching approval code in admin Connections. See [Connection setup](dot-plugin.md) |

By default, Iris reads up to 50 rows every 3 seconds and continues fetching while a backlog remains. Delivery latency depends on the KakaoTalk and redroid connection state.

## Stop and restart

```bash
docker compose down
docker compose up -d --no-build
```

`down` preserves volumes. **`down -v` deletes the login state and database.** Do not use it for routine shutdown.

Automatic restarts are disabled for redroid to avoid repeated failures. Start it with `docker compose start redroid` when needed. Other long-running services use `unless-stopped`. For automatic recovery on Linux, adjust the paths in `deploy/kakaocollector-supervisor.service.example` and install it. The supervisor limits redroid restarts to three within 30 minutes.

## Storage locations

KakaoTalk Bridge retains existing deployment identifiers for compatibility: `kakaotalk-collector` in Compose project and local image names, the Android package `dev.kakaocollector.bridge`, and the manual Lima path `/srv/kakaotalk-collector`. The new installer's VM path is `/srv/kakaotalk-bridge`; release images use `ghcr.io/rokrokss/kakaotalk-bridge-*`. Keep `COMPOSE_PROJECT_NAME` in your existing `.env` when applying the rename so that the same login and message volumes are used.

| Volume | Contents |
| --- | --- |
| `android-data` | KakaoTalk session and local database; registration app data |
| `collector-data` | Collected messages and server cursors |
| `device-state` | Registration epoch and ADB keys |
| `iris-state` | Iris collector ADB keys |
| `admin-state` | Encrypted owner password record and revocable browser sessions |
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

Stop redroid, then save `android-data` and `device-state` together in an encrypted host snapshot. Do not run the original and restored instances simultaneously with the same account. Create a new registration epoch after restoring:

```bash
docker compose --profile setup run --rm bootstrap bootstrap --rotate-epoch
```

This requires secondary-login confirmation again. Iris rereads remaining database rows under the new epoch, which may duplicate previously stored records.

`admin-state` and `dot-state` are not included in the collection database backup. Stop admin before copying `admin-state`; stop both dot-plugin and dot-control before copying `dot-state`, or use SQLite's online backup API. Preserve the matching `secrets/admin_token` and `secrets/mcp_storage_key`. Copying only a database file while it is running may omit data in the WAL. Prefer the [full snapshot command](onboarding.md#maintain-and-recover) for installations managed by `./bridge`.

## Renew certificates

The default TLS certificate lasts 365 days. Include the same gateway IP in the SAN when renewing it, then restart the gateway. The registration app's trusted certificate must also be updated through bootstrap, so schedule time to reconfirm the login sessions. Changing the Bridge signing key prevents app updates.
