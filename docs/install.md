# Linux installation

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
docker compose build api device-agent
docker compose up -d
docker compose ps
```

Python, the JDK, and the Android SDK are prepared inside the images. Android build tools use amd64 binaries, so arm64 build machines need amd64 execution support. Otherwise, build the arm64 runtime images on a separate build machine and transfer them. The KakaoTalk APK must also support redroid's ABI.

## 4. Open the admin console

For a remote server, open a tunnel from your computer:

```bash
ssh -N -L 18443:127.0.0.1:8443 user@linux-server
```

Open `https://localhost:18443/admin/` in your browser, or `https://localhost:8443/admin/` on the server itself. Verify the generated `secrets/tls_cert.pem` and configure your browser to trust it.

Authenticate with `secrets/admin_token`, then select **Installation → Prepare installation… → Install**. This deploys the KakaoTalk APK, registration app, keyboard, and Iris. Iris does not open as a separate app on the Android screen.

Follow the [first login procedure](web-ui.md#first-login). Reinstalling resets collection approval, so do not use it as a routine recovery step on a server that is already collecting messages.

## 5. Verify collection and connect

After confirming both login sessions, select **Start collecting messages** in the admin console. Send yourself a message from your phone and verify that it appears through the [API](api.md) or [ChatGPT](dot-plugin.md).

See [Operations](operations.md) for management commands and backups.
