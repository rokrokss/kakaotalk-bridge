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
./bridge passkey-login
```

The manifest selects immutable server, device and gateway image digests for Linux arm64 and amd64. The current installer requires all three; an older two-image manifest needs a new release. Until a release has been published, build the checkout instead:

```bash
./bridge install --source
./bridge passkey-login
```

Source builds compile the Android components and take longer. On a Mac these builds run inside Lima; Docker Desktop is not required. First boot downloads Ubuntu and container dependencies. The default VM is `kakaotalk-bridge`; it is separate from the older `kakaotalk-test` development VM. To avoid an existing local HTTPS port, use `./bridge install --source --admin-port 19443` on the first install.

Running install again preserves existing keys and containers. Use `update` to change images. It does not import an existing deployment from a different VM or directory. Do not copy only Android data into a new installation: it must remain paired with the original enrollment, API data and keys.

## Register a passkey and open admin

After installation, run `./bridge passkey-login`. It opens a one-use registration link on localhost; use [SSH forwarding](quickstart.md#local-and-ssh-admin-access) for a remote server. Existing HTTPS admin origins are reused. Keep that link private. Choose **Create a passkey** and save it to your device or password manager. No developer account or admin password is required. See [passkey setup and recovery](passkeys.md) for other reverse proxies and existing deployments.

Bookmark the admin address. Use **Keep me signed in** for seven days, or leave it unchecked for a 30-minute session. Sessions survive container restarts and can be revoked under **Tablet & settings → Admin browsers**. `./bridge admin` opens the same address as a convenience.

Optional shared HTTPS deployments can use one stable hostname and port 443:

| Address | Access |
| --- | --- |
| `https://<node>.ts.net/admin/` | Public login page; management requires passkey authentication |
| `https://<node>.ts.net/mcp` | Public Funnel, with MCP OAuth and passkey approval |

`./bridge setup-connection --method tailscale` enables optional Tailscale Funnel, which supplies the trusted certificate. The wizard preserves an existing localhost admin origin and configures code approval there. For a shared HTTPS admin/MCP deployment, use the configured hostname rather than localhost; passkeys are bound to that hostname. Tailscale identity headers do not replace passkey authentication. Never point Funnel at the admin/API gateway.

`expose` refuses to overwrite unrelated Tailscale routes. For an existing setup with manually managed routes, point Funnel on port 443 at the shared `dot-ingress` HTTP port, then run `./bridge connect --url https://<node>.ts.net` and `./bridge passkey-login --url https://<node>.ts.net --public-url https://<node>.ts.net`. The automatic Mac installer forwards ingress to `127.0.0.1:18787`; the older development tunnel uses 18788. `expose` removes an older Bridge-owned 8443 route only after verifying ownership of the entire current configuration. Existing passkeys remain valid on the same hostname; the origin change invalidates previous browser sessions and pending authentication flows.

Add a backup passkey under **Tablet & settings → Passkeys and recovery**. If every key is lost, run `./bridge passkey-login --enroll` on the server. `./bridge admin --recovery` can also issue a one-time link for a 30-minute emergency session. Password/key login is available only with explicit `ADMIN_AUTH_MODE=local`.

## Install KakaoTalk and verify both sessions

1. After admin sign-in, let **KakaoTalk setup** prepare the device automatically. For a fresh device this sets Korean, restarts the Android framework and installs the pinned F-Droid Aurora release after checking its SHA-256. It skips an existing KakaoTalk or Bridge installation. Manual recovery actions remain under **Tablet & settings → Installation**.
2. In Aurora, use anonymous sign-in, allow installation when Android asks, and install **KakaoTalk by Kakao Corp.** This step uses the tablet screen. Aurora is an unofficial Play client; service availability can change.
3. Bridge detects installation and configures components automatically. The server verifies KakaoTalk's APK signatures, installs Bridge and Iris and creates enrollment. If enrollment already exists, it preserves the existing approval and app data. A failed operation stops for review; use **Retry preparation** after resolving the problem.
4. Open KakaoTalk. Before signing in, select **다른 기기와 함께 사용** and run **Check login options**. Stop if that option is missing or a primary-device transfer is requested. Then complete the KakaoTalk login yourself.
5. Open KakaoTalk on your phone and verify the existing session still works. Select both confirmation boxes in admin, then start collection. These are manual observations, not an automatic guarantee about the phone session.
6. Under **Tablet & settings → Collection test and maintenance**, start a **Collection test**, then send yourself a message from your phone. Admin reports any newly received row without showing its content; it does not match a unique test message. Once an AI client is connected, retrieve the exact message to verify its content.

The guide tracks **Prepare → Sign in → Collect**. Once collection is running,
admin starts with the compact **Your bridge** overview; setup and tablet controls
are collapsed. AI connections and events remain optional.

The pre-login check understands the Korean UI. Setting Korean before installation lets Play select the Korean language split. If you installed in English already, use Aurora's manual download for the same version with the Korean locale, or import the matching Korean APK split set. Do not uninstall an already signed-in app to change language.

If Aurora is unavailable, export the official APKs from your phone or provide a complete matching set:

```bash
./bridge import-apks /path/to/apk-folder
```

The command copies APKs into the runtime; automatic preparation or **Set up collection components** verifies and installs them. It refuses to mix with a previously imported set. The current trusted Kakao signer is pinned in `device/setup.py`. A legitimate signer rotation requires an independently verified code update; the check is not bypassed automatically. No Kakao APK or account credential is redistributed with this repository.

## Connect an AI client (optional)

In admin, open **AI connections → Add or change a connection**. First choose where
you will use your messages: ChatGPT, a local AI app, another remote AI client, or
**Decide later**. Then choose from the relevant connection methods. **All
connection options** shows stdio, your own HTTPS proxy, optional Tailscale Funnel
and optional personal OpenAI tunnel together. Existing connections are retained,
and collecting messages does not require any of these providers.

The web wizard saves the settings, starts the required services, and reports the
current stage and elapsed time. Reopening or refreshing the page resumes status
monitoring and retains the last successfully saved method. Checks do not replace
that choice. Existing settings start collapsed under **Connection settings**;
saved connection instructions remain visible after checks and failures. Only one
setup job runs at a time. For Tailscale, follow the displayed sign-in/approval link
and choose **Continue setup**. On Mac, this uses Tailscale inside the managed
Linux VM. Existing unrelated Funnel/Serve routes are preserved and block automatic
setup if they conflict. Your own HTTPS reverse proxy must already route to the
MCP ingress; the wizard does not configure DNS or a third-party proxy. The HTTPS
field accepts the origin or its full `/mcp` URL and normalizes it for you.

The HTTPS choices start the OAuth services and configure consent automatically.
Add the printed `/mcp` address in your AI client with OAuth authentication. For
local/private admin, match the code in **AI connections** and approve the request.
For shared HTTPS admin/MCP, confirm with your passkey and review permissions in
the connecting browser. Requests expire in ten minutes. Disconnect clients from
admin at any time. OAuth retains its browser binding, Origin checks, redirect
validation and PKCE.

The OpenAI web form takes the tunnel ID, a password-masked runtime key and an
explicit permission checkbox. It configures the service and allows this personal
tunnel until you disconnect it. A saved key can be reused for the same tunnel ID.
Creating the tunnel in your OpenAI workspace
and selecting it in ChatGPT remain provider steps. See [tunnel setup](openai-tunnel.md).

The stdio option provides copyable client configuration for `./bridge mcp`; it
needs no OAuth or public URL. Enter an SSH destination for a remote installation.
That SSH account needs noninteractive authentication and Docker access. The web
check verifies running server services; confirm the complete connection by asking
your AI for collector status and retrieving a test message. The overview and
connection cards show approval separately from the last successful remote tool
call. Earlier calls are not backfilled, and stdio activity is not recorded there.
Connecting any client does not create an event subscription.

On failure, read the stage-specific message and select **Review and retry** to
review settings before submitting again. A failed server check offers **Check
again**. An interrupted job reopens for review; it does not silently resume a
mutation. See the [admin guide](web-ui.md#progress-and-recovery) for details.

The CLI wizard `./bridge setup-connection` remains available. `./bridge up`
installs/restarts the private web setup agent under systemd. For an existing
installation, update source and images first, then run `./bridge up`. On Linux
without systemd, run `./bridge --local setup-agent serve` under your service
manager as root. It needs the installation directory and Docker access. If the
agent is unavailable, admin shows recovery instructions rather than claiming
that setup succeeded.

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
