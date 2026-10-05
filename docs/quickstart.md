# Install and open KakaoTalk Bridge

Run one command again whenever you want to start Bridge. It prepares the runtime,
starts the services, configures a secure browser address and opens setup. Your
existing installation, keys and KakaoTalk session are reused. It does not update
an existing installation's images or move an older deployment into a new VM.

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

## Download and start

After this installer has been published to the repository's main branch:

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

The first run downloads source and builds the server images. This can take a
while. Later runs reuse the installed copy. Downloads use HTTPS and official
dependency installers; your OS may ask for administrator approval. The installer
may prepare Python through uv, Homebrew/Lima on Mac, Docker on Linux, and Tailscale.
It does not change your shell startup files.

The default location is `~/Library/Application Support/KakaoTalk Bridge` on Mac
and `${XDG_DATA_HOME:-~/.local/share}/kakaotalk-bridge` on Linux. Set `BRIDGE_HOME`
to choose another location. `BRIDGE_VERSION` selects a source tag or commit for a
fresh download; it does not update an existing copy. When run from a checkout,
`bash install.sh` uses that checkout unless `BRIDGE_HOME` is specified.

For a verified prebuilt release, use `./bridge up --manifest /path/to/release.json`
after verifying the manifest as described in [onboarding](onboarding.md).
Unpublished release images are not assumed to exist.

## What you do in the browser

1. On first use, sign in to Tailscale when prompted. It supplies the trusted HTTPS
   address. Enable HTTPS/Funnel if its permission link asks you to do so. Both
   `/admin/` and `/mcp` use this address on HTTPS port 443. The admin login page is
   public; management requires your passkey, and MCP requires OAuth.
2. Save a passkey to protect your bridge. Returning users use the saved passkey.
3. Device preparation starts automatically after admin sign-in. If KakaoTalk is
   not installed, choose anonymous sign-in in the on-screen Aurora store and
   install **KakaoTalk by Kakao Corp.** Bridge detects installation, verifies the
   publisher, installs collection components and opens KakaoTalk automatically.
4. Select **다른 기기와 함께 사용**, run **Check login options**, and complete
   KakaoTalk sign-in. Confirm that your phone is still signed in, check both boxes,
   and start collection. These confirmations are never automated.
5. Use **Connections** to connect your AI client and send yourself a test message.

Store consent, app installation, passkey creation and account verification cannot
be silently completed on the user's behalf. If you already have the complete
official APK set, `./bridge up --apk-folder /path/to/apks` skips store installation.
Identical imports are safe to repeat; different sets are not mixed. No KakaoTalk
APK or account credential is distributed with Bridge.

Preparation stops after a failed operation instead of retrying mutations in a
loop. Use **Retry preparation** or **Check again** after resolving it. Existing
enrollment and collection approval are preserved. [Login details](web-ui.md#first-login)

## Platforms

| Environment | Execution path | Current validation |
| --- | --- | --- |
| Apple Silicon Mac | Automatic dedicated Lima Ubuntu VM; Docker Desktop not needed | Fresh VM source installation and real browser/OAuth tested; see scope below |
| Intel Mac | Lima with QEMU, installed when missing | Code path provided; real installation unverified |
| Ubuntu/Debian Linux | Local Docker Engine; attempt to load/install Binder modules | `bridge up` tested inside the prepared Ubuntu VM; fresh standalone host still unverified |
| Other Linux | Reuse compatible installed tools and Binder | Missing unsupported prerequisites produce an actionable error |
| Windows with a Linux server | PowerShell starts setup over SSH; HTTPS opens in the Windows browser | Script provided; Windows execution unverified |
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

Open the setup link it prints in the Windows browser. Tailscale supplies the
server’s shared HTTPS address. Windows OpenSSH is required;
no Windows Tailscale client is required for the shared public HTTPS address. Windows execution policy may require you to
unblock a downloaded script under your organization's policy.

For an already configured Binder-enabled WSL2 distribution:

```powershell
.\install.ps1 -Distribution Ubuntu
```

The script stops before changing anything if the distribution lacks loaded Binder
support. It does not install WSL, replace its shared kernel or delete a distribution.
The Windows entry point downloads the published Unix installer, so it is usable
after this change is published.

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

For OpenAI access without a public MCP address, see [personal tunnel setup](openai-tunnel.md).
Use `--connection openai-tunnel --admin-url https://your-private-admin-host`
with `--tunnel-id` and `--api-key-file` on first setup. This skips Tailscale
installation and Funnel configuration. Your browser still needs trusted HTTPS
access to the admin console; an existing private Tailscale Serve address also works.

The collector API, ADB and passkey control service remain internal. Keep using the
same hostname so saved passkeys remain valid. Advanced deployments may still use
`--admin-url` and `--public-url` with the same hostname and different ports; to keep
admin tailnet-only, their public proxy must explicitly reject `/admin` and `/admin/*`.

The VM retains separate internal maintenance and ingress listeners. Users access
one HTTPS port. On a fresh Mac installation, Bridge chooses free local ports and
saves them before the VM starts. Retries and subsequent launches reuse those
ports. Explicitly requested ports fail with a clear error if already occupied.

For image changes and encrypted backups, follow [operations](operations.md).
`up` does not upgrade running images. Automated host tests do not establish that
a clean installation, Tailscale approval, store installation and KakaoTalk login
have succeeded on every operating system.
