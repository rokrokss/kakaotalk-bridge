# Set up a personal bridge

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
./bridge admin
```

The manifest selects immutable image digests for Linux arm64 and amd64. Until a release has been published, build the checkout instead:

```bash
./bridge install --source
./bridge admin
```

Source builds compile the Android components and take longer. On a Mac these builds run inside Lima; Docker Desktop is not required. First boot downloads Ubuntu and container dependencies. The default VM is `kakaotalk-bridge`; it is separate from the older `kakaotalk-test` development VM. To avoid an existing local HTTPS port, use `./bridge install --source --admin-port 19443` on the first install.

Running install again preserves existing keys and containers. Use `update` to change images. It does not import an existing deployment from a different VM or directory. Do not copy only Android data into a new installation: it must remain paired with the original enrollment, API data and keys.

## Open admin without copying a permanent key

`./bridge admin` opens a one-time link. It expires after ten minutes and is consumed only when you submit the pairing form. A newly issued link invalidates the previous one. The secret stays in the URL fragment and is removed from the browser address immediately; it is not sent in HTTP URLs.

On the first visit, choose an admin password of at least 12 characters. This is separate from your KakaoTalk password. Use **Keep me signed in** for seven days, or leave it unchecked for a 30-minute session. Sessions survive container restarts and can be revoked under **Admin browsers**.

For localhost HTTPS, trust the installation's `secrets/tls_cert.pem` after verifying it. On the automatic Mac installation this file is inside Lima at `/srv/kakaotalk-bridge/secrets/tls_cert.pem`; copy only that public certificate to the Mac for browser trust. For a remote Linux server, run `ssh -N -L 18443:127.0.0.1:8443 user@linux-server` on your computer, then run `./bridge admin --url https://localhost:18443` on the server; open the resulting link on the computer with the tunnel.

For a trusted certificate and access from your other devices, sign in to Tailscale on the server and run:

```bash
./bridge expose
./bridge admin
```

This configures two separate endpoints:

| Address | Access |
| --- | --- |
| `https://<node>.ts.net:8443/admin/` | Private tailnet, with admin authentication |
| `https://<node>.ts.net/mcp` | Public Funnel, with OAuth |

The command preserves unrelated existing Tailscale routes by refusing to overwrite them. For an existing Tailscale setup, configure Serve on port 8443 to the local admin HTTPS port and Funnel on port 443 to the local MCP HTTP port yourself, then run `./bridge connect --url https://<node>.ts.net`. The automatic Mac installer forwards the MCP port to `127.0.0.1:18787`; the older development tunnel uses 18788. Never point Funnel at the admin/API gateway.

Pairing/password authentication remains required; forwarded Tailscale identity headers do not bypass it. Passkeys and identity-based Tailscale sign-in are not implemented.

If you lose the password, run `./bridge reset-password`, followed by `./bridge admin`. Resetting revokes all admin browser sessions. The existing `secrets/admin_token` remains a recovery option. Neither action signs out of KakaoTalk.

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
2. Add the `/mcp` address shown under **Connections** in ChatGPT, with OAuth authentication.
3. The authorization page displays a one-time eight-character code. Open private admin **Connections**, check the client ID and callback, type that code, and approve. Client names are self-reported.
4. The connecting page continues automatically after approval. The request expires after ten minutes. You can disconnect a client in admin at any time.

OAuth still requires the initiating browser cookie, exact Origin, redirect URI, resource and PKCE challenge. The approval listener has no host port and runs only on the internal backend network. Connecting does not create an event subscription.

## Maintain and recover

```bash
./bridge doctor
./bridge backup
./bridge update --manifest release.json
```

`doctor` prints service state and missing prerequisites without message bodies, tokens or raw logs. `backup` briefly stops the stack, encrypts an offline snapshot with AES-256-GCM, then starts the previously running services. The snapshot includes all six state volumes, `.env` and `secrets/`, preserving Android ownership, permissions, links and extended attributes. Unix sockets are recreated by their processes. Keep enough disk space for both the archive and restored data.

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

Authentication is verified before extraction. Restore writes new volumes and switches the configuration only after validation. The previous volumes and configuration remain available; nothing runs a `down -v`. Failed configuration activation is rolled back, including after a process interruption. Browser sessions, OAuth grants and event callbacks are cleared, while the admin password and profile identity are preserved. Reconnect ChatGPT, recreate explicitly requested event subscriptions and check both KakaoTalk sessions again. A saved Android session may still be rejected by Kakao's servers.

Update pulls/builds before stopping anything, makes an encrypted snapshot, then checks container health. A failed health check restores the previous image selection. It never reinstalls the signed-in KakaoTalk or Bridge app. If an image changes the bundled Iris APK, update stops before deployment: that requires a separate, tested component migration. Switching a personal Bridge signing key to a release signing key is not automated.

## Release maintainers

The release workflow runs on `vMAJOR.MINOR.PATCH` tags, builds both architectures, publishes SBOM/provenance metadata and attaches `release.json` to a versioned release. Configure the protected GitHub `release` environment with a stable `BRIDGE_RELEASE_KEYSTORE_BASE64` and `BRIDGE_RELEASE_KEY_PASSWORD` before publishing. Keep that signing identity across releases. Do not rotate it in an ordinary update.

Publish both GHCR image packages as public for installation without registry credentials. The installer does not log in to GHCR. Image names are `ghcr.io/rokrokss/kakaotalk-bridge-server` and `ghcr.io/rokrokss/kakaotalk-bridge-device`.

The workflow and installer are implemented; a release must actually be published before the prebuilt installation command can download those images. Local image builds and isolated tests do not establish a successful clean install on every supported host.
