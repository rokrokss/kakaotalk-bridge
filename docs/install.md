# Linux installation

For automatic installation, passkey admin login, optional web-based AI setup and full encrypted snapshots, start with [one-command setup](quickstart.md). It requires neither Tailscale nor an OpenAI tunnel. The commands below describe the existing manual deployment path with a configured HTTPS admin address.

[README](../README.md) · [Mac installation](local-redroid.md)

This Docker Compose stack supports one account on Linux amd64/arm64. It requires Docker Engine, Compose v2, Bash, OpenSSL, and Android binder/binderfs. Start with 4 vCPUs and 8 GB RAM; these are suggested starting resources, not measured minimum requirements.

## 1. Prepare configuration and keys

Run from the repository root:

```bash
cp .env.example .env
./scripts/preflight.sh
```

If `preflight` fails, resolve the Linux kernel and binder configuration first. Shared memory uses `androidboot.use_memfd=1`.

Check that `DEVICE_SUBNET` in `.env` does not overlap your LAN, VPN, or other Docker networks. If you change it, update `GATEWAY_IP` and `DEVICE_IP_RANGE` as well, keeping the fixed gateway address outside the automatic allocation range. The defaults are `172.29.87.0/24`, `172.29.87.3`, and `172.29.87.128/25`, respectively.

```bash
./scripts/init-secrets.sh
```

This script preserves existing keys. Keep `.env` in shell-compatible `KEY=value` format, and retain the generated `secrets/` directory and Bridge signing key.

## 2. Prepare the KakaoTalk APK

Place official installation files in `inputs/kakao/`. Split APKs require the complete installation set with matching versions and signatures. This directory can be empty if KakaoTalk is already installed in redroid.

To import APKs from an Android phone connected over USB, install ADB and the Python development environment on the host. Enable USB debugging on the phone, then run:

```bash
uv sync --frozen --python 3.12
uv run python scripts/import-phone-apks.py
```

This command copies APKs only. It does not change the phone's app data or login settings. KakaoTalk APKs and account credentials are not included in the images.

## 3. Build and start

```bash
docker compose build api device-agent gateway
docker compose up -d
docker compose ps
```

Python, the JDK, and the Android SDK are prepared inside the images. Android build tools use amd64 binaries, so arm64 build machines need amd64 execution support. Otherwise, build the arm64 runtime images on a separate build machine and transfer them. The KakaoTalk APK must also support redroid's ABI.

## 4. Open the admin console

Configure a stable, trusted HTTPS hostname using private Tailscale Serve or your
reverse proxy, then register a [passkey](passkeys.md). For local/SSH admin without
Tailscale, use the [automatic setup path](quickstart.md#local-and-ssh-admin-access).

If you explicitly want public MCP through Tailscale Funnel, the CLI can prepare
it and configure approval while preserving an existing admin origin:

```bash
./bridge expose
./bridge passkey-login
```

Open the admin address printed by `passkey-login` and confirm with your passkey.
Existing private addresses such as `https://<node>.ts.net:8443/admin/` remain
separate from public MCP; new shared HTTPS configurations use `/admin/` and
`/mcp` on port 443. A localhost passkey cannot be used at a public hostname:
split-origin setup uses code approval in admin instead. Keep your configured
admin origin stable.

Follow **KakaoTalk setup**, using the screen under **Tablet & settings** to install
KakaoTalk through Aurora or importing an APK set. Component setup continues
automatically; **Installation → Set up collection components** remains available
for manual recovery.

Follow the [first login procedure](web-ui.md#first-login). The new setup action preserves existing enrollment. The legacy CLI `bootstrap` still resets collection approval and is not a routine recovery step.

## 5. Verify collection and connect

After confirming both login sessions, select **Start collecting messages** in the admin console. Send yourself a message from your phone and verify that it appears through the [API](api.md) or [ChatGPT](dot-plugin.md).

AI access is optional. The [web connection setup service](operations.md#web-connection-setup)
enables **AI connections → Add or change a connection** on this manual install;
otherwise use `./bridge setup-connection`. Keep the existing admin origin and keys.

See [Operations](operations.md) for management commands and backups.
