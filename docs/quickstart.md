# Install and open KakaoTalk Bridge

Run one command again whenever you want to start Bridge. It prepares the runtime,
starts the services and opens a local admin setup page. No external AI connection
is configured by default. Your
existing installation, keys and KakaoTalk session are reused. It does not update
an existing installation's images or move an older deployment into a new VM.

## Download and start

On macOS or Linux, open Terminal on the machine that will run Bridge and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

You do not need to clone or download the project first.
The first run downloads source and builds the server images. This can take a
while. Later runs reuse the installed copy. Downloads use HTTPS and official
dependency installers; your OS may ask for administrator approval. The installer
may prepare Python through uv, Homebrew/Lima on Mac, and Docker on Linux. Tailscale is installed only when explicitly selected.
It does not change your shell startup files.

The terminal shows short English progress messages and confirms each completed
step. Long setup steps print an elapsed-time update every 30 seconds. Detailed
command output goes to a private log in `.bridge/logs/` inside the installation;
early Python/download preparation uses a separate temporary log. Log paths are
printed, including when a step fails. Password prompts, dependency installer
confirmations and browser sign-in instructions remain visible. One-time setup
and sign-in links are not written to these logs.

To show detailed command output directly while troubleshooting:

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash -s -- --verbose
# Or, from a downloaded source checkout:
./bridge up --verbose
```

The default location is `~/Library/Application Support/KakaoTalk Bridge` on Mac
and `${XDG_DATA_HOME:-~/.local/share}/kakaotalk-bridge` on Linux. Set `BRIDGE_HOME`
to choose another location. `BRIDGE_VERSION` selects a source tag or commit for a
fresh download; it does not update an existing copy. When run from a checkout,
`bash install.sh` uses that checkout unless `BRIDGE_HOME` is specified.

For a verified prebuilt release, use `./bridge up --manifest /path/to/release.json`
after verifying the manifest as described in [onboarding](onboarding.md).
Unpublished release images are not assumed to exist.

## From a downloaded source checkout

On macOS or Linux, run this in the project folder:

```bash
bash install.sh
```

The installer prepares Python if needed. Once Python is available, `./bridge up`
does the same work. To inspect the steps without installing, starting or changing
anything:

```bash
./bridge up --plan
```

## What you do in the browser

1. Open the printed localhost link. On a remote server, first establish the SSH
   forwarding session described below. Existing installations keep their admin address.
2. Save a passkey to protect your bridge. Returning users use the saved passkey.
3. Device preparation starts automatically after admin sign-in. If KakaoTalk is
   not installed, choose anonymous sign-in in the on-screen Aurora store and
   install **KakaoTalk by Kakao Corp.** Bridge detects installation, verifies the
   publisher, installs collection components and opens KakaoTalk automatically.
   Follow the on-page steps for store sign-in, Android installation permission
   and search, or use the [detailed Aurora guide](web-ui.md#install-kakaotalk-in-aurora).
4. Select **다른 기기와 함께 사용**, run **Check login options**, and complete
   KakaoTalk sign-in. Confirm that your phone is still signed in, check both boxes,
   and start collection. These confirmations are never automated.
5. Send yourself a test message to check collection. When ready, open **AI
   connections → Add or change a connection** in admin. Choose where you will use
   your messages, or leave AI connections for later. The terminal alternative is
   `./bridge setup-connection`.

Store consent, app installation, passkey creation and account verification cannot
be silently completed on the user's behalf. If you already have the complete
official APK set, `./bridge up --apk-folder /path/to/apks` skips store installation.
Identical imports are safe to repeat; different sets are not mixed. No KakaoTalk
APK or account credential is distributed with Bridge.

Preparation stops after a failed operation instead of retrying mutations in a
loop. Use **Retry preparation** or **Check again** after resolving it. Existing
enrollment and collection approval are preserved. [Login details](web-ui.md#first-login)

Once collecting, the **Your bridge** overview replaces the expanded setup view.
It shows collection, remote AI activity and your manual phone confirmation.
Open **Tablet & settings** when you need the screen, installation, passkeys or
recovery controls. A phone recheck reminder does not mean a sign-out was detected.

## Connect an AI when ready

Open **AI connections → Add or change a connection** and choose where you will
use your messages. **ChatGPT** offers a personal OpenAI tunnel or HTTPS;
**An AI app on my computer** offers stdio, including SSH; **Another remote AI
client** offers your existing HTTPS address or Tailscale Funnel. **Decide later**
keeps your current setup. Both Tailscale and OpenAI tunnels are optional, and
multiple connection methods can coexist.

Enter the requested settings and follow the progress shown in admin. HTTPS accepts
the origin or a full `/mcp` URL. Tunnel setup takes its ID and runtime key and
includes explicit access approval. Tailscale may require a provider sign-in and
**Continue setup**. Finish adding the connection in your AI client using the
displayed instructions. The [client completion guide](web-ui.md#finish-in-your-ai-client)
walks through the tunnel, OAuth and local-app paths, including how to verify a
message from your phone.

Server setup/check completion and access approval are separate from a successful
AI request. Ask your AI for collector status, then retrieve your test message.
The overview records successful remote tool calls; it does not track local stdio
activity or promise ongoing reachability. Saved instructions survive checks and
reloads. Use **Connection settings** to edit or **Review and retry** after a
failure. [Detailed admin workflow](web-ui.md#ai-connections)

## Platforms

| Environment | Execution path | Current validation |
| --- | --- | --- |
| Apple Silicon Mac | Automatic dedicated Lima Ubuntu VM; Docker Desktop not needed | Fresh VM source installation and real browser/OAuth tested; see scope below |
| Intel Mac | Lima with QEMU, installed when missing | Code path provided; real installation unverified |
| Ubuntu/Debian Linux | Local Docker Engine; attempt to load/install Binder modules | `bridge up` tested inside the prepared Ubuntu VM; fresh standalone host still unverified |
| Other Linux | Reuse compatible installed tools and Binder | Missing unsupported prerequisites produce an actionable error |
| Windows with a Linux server | PowerShell starts setup over SSH and keeps localhost forwarding open | Script provided; Windows execution unverified |
| Windows WSL2 | Existing distribution with Binder already loaded | Explicit compatibility check; stock WSL2 is not claimed to work |

Validation on 2026-10-05 used an isolated Apple Silicon Lima VM with source-built
images, real Android/Aurora preparation, official KakaoTalk APK import and
signature verification, the Korean secondary-device login screen, native browser
WebAuthn with a virtual authenticator, and the real OAuth/MCP services. The MCP
callback was intercepted by the browser test. A full VM stop followed by the
same installer command completed in about 27 seconds; credentials, enrollment,
passkey login and OAuth/MCP continued working. Existing Mac prerequisites were
already installed. The source-build retry took about 22 minutes on that machine.
KakaoTalk account login, Aurora's anonymous store download, fresh Tailscale
onboarding/Funnel, Intel Mac and Windows remain outside that test. Local HTTPS
proxies kept the existing installation's Tailscale routes untouched.

Local execution needs arm64 or x86_64, sufficient memory/disk, and host access to
the required virtualization/kernel features. Restricted containers, managed
corporate machines and arbitrary kernels are not universally supported. Run the
Linux workload on a dedicated host/VM. The installer does not replace a Windows
or Linux kernel, change unrelated Tailscale routes, or switch Docker contexts.

From a source checkout on Windows, use an existing Linux server:

```powershell
.\install.ps1 -Remote user@linux-host
```

Open the setup link it prints in the Windows browser. After setup, the script
keeps an SSH forwarding session open on port 18789; Ctrl+C closes forwarding
without stopping the server. Windows OpenSSH is required. If that local port is
occupied, close the other forwarding session before retrying. Existing HTTPS
admin addresses still work directly. Windows execution policy may require you to
unblock a downloaded script under your organization's policy.

For an already configured Binder-enabled WSL2 distribution:

```powershell
.\install.ps1 -Distribution Ubuntu
```

The script stops before changing anything if the distribution lacks loaded Binder
support. It does not install WSL, replace its shared kernel or delete a distribution.
The Windows entry point downloads the published Unix installer.

## Reopen, retry, and advanced environments

Rerun the same install command to reopen the browser or resume after a restart.
A process lock prevents concurrent setup for the same installation. Only the
current step/status is saved in `.bridge/onboarding.json`; one-time browser links
are not stored there. Already running services and login data are reused.

```bash
./bridge up --no-install                  # Require already installed host tools
./bridge up --no-browser                  # Print the link on a headless server
./bridge up --admin-port 19443            # Internal maintenance port on first Mac install
./bridge up --mcp-port 19787              # Local shared ingress port on first Mac install
./bridge doctor                          # Diagnostics (sudo may be needed on Linux)
```

When the host already has an HTTPS proxy, forward its single HTTPS origin to the
shared ingress (`127.0.0.1:18787` by default), then skip Tailscale preparation:

```bash
./bridge up --url https://bridge.example.com
```

The root address redirects to `/admin/`; AI clients use `/mcp` on the same port.

For OpenAI access without a public MCP address, choose **ChatGPT → Personal
tunnel · no public address** in admin. The CLI alternative is
`./bridge setup-connection --method openai-tunnel`; it reads the runtime key
without echoing it, saves credentials and starts services. CLI provisioning
requires a separate approval in admin. Finish by selecting the tunnel in ChatGPT.
See [personal tunnel setup](openai-tunnel.md).

Admin and MCP addresses can differ. A localhost/private admin keeps its passkey;
a public OAuth connection is approved by matching its code in admin. A shared
HTTPS hostname can use direct passkey consent. To keep the public login page
private too, reject `/admin` and `/admin/*` at your public HTTPS proxy.

The VM retains separate maintenance, public ingress and local admin listeners.
On a fresh Mac installation Bridge chooses free local ports and saves them
before starting the VM. Retries reuse those ports.

## Local and SSH admin access

Fresh installs use `http://localhost:18789/admin/` (Mac can choose a free port).
Only the loopback interface is published. The local entry point serves admin,
not MCP, ADB or the collection API. Browsers allow passkeys on localhost without
a TLS certificate. Do not replace `localhost` with a LAN address.

On a headless Linux server, run `./bridge up --no-browser`. On your own computer,
keep this command running and open the printed setup link:

```bash
ssh -N -L 127.0.0.1:18789:127.0.0.1:18789 user@your-server
```

The server keeps running after SSH closes; reconnect SSH to administer it later.
`./bridge passkey-login --link-only` prints a fresh link when needed. If the local
port is occupied, use a different browser origin, for example
`./bridge passkey-login --url http://localhost:19789`, and forward local 19789 to
server 18789. Keep that chosen origin stable for returning sessions.

Use **AI connections → Add or change a connection**, or the CLI alternative
`./bridge setup-connection`, to add stdio, public HTTPS/OAuth, optional Tailscale
Funnel, or an optional OpenAI tunnel. **Decide later** keeps existing connections.
**Disconnect tunnel** revokes access; `./bridge tunnel disable` also stops its
services.

For image changes and encrypted backups, follow [operations](operations.md).
`up` does not upgrade running images. Automated host tests do not establish that
a clean installation, Tailscale approval, store installation and KakaoTalk login
have succeeded on every operating system.
