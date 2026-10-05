# Set up a personal bridge

For automatic preparation and a single launch command, start with [one-command setup](quickstart.md): `bash install.sh` or `./bridge up`. The individual commands below remain available for advanced deployments.

The installer manages one account on a Linux Docker host. On a Mac it creates a Lima VM with no home-directory mounts. The web console guides you through installing KakaoTalk, signing in as a secondary device, checking your phone, and connecting ChatGPT.

## Install

Clone the repository and run the commands from its root:

```bash
git clone https://github.com/rokrokss/kakaotalk-bridge.git
cd kakaotalk-bridge
```

Mac users need Lima (`brew install lima`); Linux users need Docker Engine, Compose v2, Bash, OpenSSL and Android binder support as described in [Linux installation](install.md). Use Python 3.12+ for the host CLI; it needs no third-party Python packages.

For a published release, download its `release.json` from this repository's GitHub Releases. Verify its provenance before installing:

```bash
gh attestation verify release.json --repo rokrokss/kakaotalk-bridge
./bridge install --manifest release.json
./bridge expose
./bridge passkey-login
```

The manifest selects immutable server, device and gateway image digests for Linux arm64 and amd64. The current installer requires all three; an older two-image manifest needs a new release. Until a release has been published, build the checkout instead:

```bash
./bridge install --source
./bridge expose
./bridge passkey-login
```

Source builds compile the Android components and take longer. On a Mac these builds run inside Lima; Docker Desktop is not required. First boot downloads Ubuntu and container dependencies. The default VM is `kakaotalk-bridge`; it is separate from the older `kakaotalk-test` development VM. To avoid an existing local HTTPS port, use `./bridge install --source --admin-port 19443` on the first install.

Running install again preserves existing keys and containers. Use `update` to change images. It does not import an existing deployment from a different VM or directory. Do not copy only Android data into a new installation: it must remain paired with the original enrollment, API data and keys.

## Register a passkey and open admin

After installation, sign in to Tailscale on the server and run `./bridge expose`, then `./bridge passkey-login`. The second command opens a one-use registration link. Keep that link private. Choose **Create a passkey** and save it to your device or password manager. No developer account or admin password is required. See [passkey setup and recovery](passkeys.md) for other reverse proxies and existing deployments.

Bookmark the admin address. Use **Keep me signed in** for seven days, or leave it unchecked for a 30-minute session. Sessions survive container restarts and can be revoked under **Admin browsers**. `./bridge admin` opens the same address as a convenience.

Both endpoints share one stable hostname and HTTPS port 443:

| Address | Access |
| --- | --- |
| `https://<node>.ts.net/admin/` | Public login page; management requires passkey authentication |
| `https://<node>.ts.net/mcp` | Public Funnel, with MCP OAuth and passkey approval |

Tailscale Funnel supplies the trusted certificate. Use the configured hostname rather than localhost; passkeys are bound to that hostname. Tailscale identity headers do not replace passkey authentication. Never point Funnel at the admin/API gateway.

`expose` refuses to overwrite unrelated Tailscale routes. For an existing setup with manually managed routes, point Funnel on port 443 at the shared `dot-ingress` HTTP port, then run `./bridge connect --url https://<node>.ts.net` and `./bridge passkey-login --url https://<node>.ts.net --public-url https://<node>.ts.net`. The automatic Mac installer forwards ingress to `127.0.0.1:18787`; the older development tunnel uses 18788. `expose` removes an older Bridge-owned 8443 route only after verifying ownership of the entire current configuration. Existing passkeys remain valid on the same hostname; the origin change invalidates previous browser sessions and pending authentication flows.

Add a backup passkey under **Passkeys and recovery**. If every key is lost, run `./bridge passkey-login --enroll` on the server. `./bridge admin --recovery` can also issue a one-time link for a 30-minute emergency session. Password/key login is available only with explicit `ADMIN_AUTH_MODE=local`.

## Install KakaoTalk and verify both sessions

1. In the setup guide, choose **Prepare tablet**. For a fresh device this sets Korean, restarts the Android framework and installs the pinned F-Droid Aurora release after checking its SHA-256. It skips an existing KakaoTalk or Bridge installation.
2. In Aurora, use anonymous sign-in, allow installation when Android asks, and install **KakaoTalk by Kakao Corp.** This step uses the tablet screen. Aurora is an unofficial Play client; service availability can change.
3. Refresh setup and choose **Set up components**. The server verifies KakaoTalk's APK signatures, installs Bridge and Iris and creates enrollment. If enrollment already exists, it preserves the existing approval and app data.
4. Open KakaoTalk. Before signing in, select **다른 기기와 함께 사용** and run **Check login options**. Stop if that option is missing or a primary-device transfer is requested. Then complete the KakaoTalk login yourself.
5. Open KakaoTalk on your phone and verify the existing session still works. Select both confirmation boxes in admin, then start collection. These are manual observations, not an automatic guarantee about the phone session.
6. Start a **Collection test**, then send yourself a message from your phone. Admin reports a newly received row without showing its content. Ask ChatGPT for the message to verify the content.

The pre-login check understands the Korean UI. Setting Korean before installation lets Play select the Korean language split. If you installed in English already, use Aurora's manual download for the same version with the Korean locale, or import the matching Korean APK split set. Do not uninstall an already signed-in app to change language.

If Aurora is unavailable, export the official APKs from your phone or provide a complete matching set:

```bash
./bridge import-apks /path/to/apk-folder
```

The command copies APKs into the runtime; **Set up components** verifies and installs them. It refuses to mix with a previously imported set. The current trusted Kakao signer is pinned in `device/setup.py`. A legitimate signer rotation requires an independently verified code update; the check is not bypassed automatically. No Kakao APK or account credential is redistributed with this repository.

## Connect ChatGPT

1. Run `./bridge expose`, or supply a public HTTPS reverse proxy and run `./bridge connect --url https://your-host`.
2. Register your [passkey](passkeys.md) for the shared admin/MCP origin, then add the `/mcp` address in ChatGPT with OAuth authentication.
3. Confirm with your passkey, then review the client, callback and requested permissions. Client names are self-reported.
4. Choose **Allow connection** to return to ChatGPT, or **Cancel** to decline. The request expires after ten minutes. You can disconnect a client in admin **Connections** at any time.

OAuth still requires the initiating browser cookie, exact Origin, redirect URI, resource and PKCE challenge. The approval listener has no host port; separate internal networks distinguish private administration from public passkey assertions. The shared port belongs to dot-ingress, which routes `/admin/*` to admin and filters admin cookies before forwarding OAuth/MCP traffic. Connecting does not create an event subscription.

## Maintain and recover

```bash
./bridge doctor
./bridge backup
./bridge update --manifest release.json
```

`doctor` prints service state and missing prerequisites without message bodies, tokens or raw logs. `backup` briefly stops the stack, encrypts an offline snapshot with AES-256-GCM, then starts the previously running services. The snapshot includes all seven state volumes, `.env` and `secrets/`, preserving Android ownership, permissions, links and extended attributes. Unix sockets are recreated by their processes. Keep enough disk space for both the archive and restored data.

Backups are written to `backups/*.kcs`; on a Mac they are copied out of Lima automatically. **Keep `secrets/backup_key` separately**: the copy inside the encrypted archive cannot unlock that archive. For the automatic Mac installation, export this one file privately:

```bash
umask 077
limactl shell --workdir=/ kakaotalk-bridge sudo cat /srv/kakaotalk-bridge/secrets/backup_key > /your/private/location/backup_key
```

To restore into an initialized installation using the same code release:

```bash
./bridge stop
./bridge restore /path/to/snapshot.kcs --key /path/to/backup_key
./bridge start
./bridge admin
```

Authentication is verified before extraction. Restore writes new volumes and switches the configuration only after validation. The previous volumes and configuration remain available; nothing runs a `down -v`. Failed configuration activation is rolled back, including after a process interruption. Browser sessions, OAuth grants and event callbacks are cleared, while passkey credentials and configuration, any local password and profile identity are preserved. Reconnect ChatGPT, recreate explicitly requested event subscriptions and check both KakaoTalk sessions again. A saved Android session may still be rejected by Kakao's servers.

Update pulls/builds before stopping anything, makes an encrypted snapshot, then checks container health. A failed health check restores the previous image selection. It never reinstalls the signed-in KakaoTalk or Bridge app. If an image changes the bundled Iris APK, update stops before deployment: that requires a separate, tested component migration. Switching a personal Bridge signing key to a release signing key is not automated.

## Release maintainers

The release workflow runs on `vMAJOR.MINOR.PATCH` tags, builds both architectures, publishes SBOM/provenance metadata and attaches `release.json` to a versioned release. Configure the protected GitHub `release` environment with a stable `BRIDGE_RELEASE_KEYSTORE_BASE64` and `BRIDGE_RELEASE_KEY_PASSWORD` before publishing. Keep that signing identity across releases. Do not rotate it in an ordinary update.

Publish all three GHCR image packages as public for installation without registry credentials. The installer does not log in to GHCR. Image names are `ghcr.io/rokrokss/kakaotalk-bridge-server`, `ghcr.io/rokrokss/kakaotalk-bridge-device` and `ghcr.io/rokrokss/kakaotalk-bridge-gateway`.

The workflow and installer are implemented; a release must actually be published before the prebuilt installation command can download those images. Local image builds and isolated tests do not establish a successful clean install on every supported host.
