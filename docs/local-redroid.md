# Running on an Apple Silicon Mac

For the new installer, browser pairing, Aurora setup and full encrypted snapshots, see [Set up a personal bridge](onboarding.md). The commands below describe the existing manual deployment path.

[README](../README.md) · [Admin console](web-ui.md) · [Connect ChatGPT](dot-plugin.md)

Docker containers run inside a Lima Ubuntu 24.04 arm64 VM. Docker Desktop is used for image builds. The supplied configuration allocates 6 CPUs, 8 GiB RAM, and a 40 GiB virtual disk. It does not mount the Mac home directory into the VM.

## 1. Prepare and build

Install Lima through Homebrew and install Docker Desktop. Run from the repository root. For an existing installation, reuse its `.env` and keys.

```bash
cp .env.example .env
./scripts/init-secrets.sh
docker compose build api device-agent
```

If networks overlap, adjust `.env` before generating keys. The requirements match [Linux installation](install.md#1-prepare-configuration-and-keys). Place KakaoTalk APKs in `inputs/kakao/` or [import them from a connected Android phone](install.md#2-prepare-the-kakaotalk-apk).

## 2. Create the VM and transfer files

```bash
limactl start --name=kakaotalk-test --tty=false deploy/lima.yaml
limactl shell --workdir=/ kakaotalk-test sudo mkdir -p /srv/kakaotalk-collector
```

The following copies the current commit's source and local configuration to a new VM. When updating an existing VM, take care not to overwrite its keys or `.env`.

```bash
set -o pipefail
git archive HEAD |
  limactl shell --workdir=/ kakaotalk-test sudo tar --no-same-owner -xf - -C /srv/kakaotalk-collector
COPYFILE_DISABLE=1 tar --no-xattrs -cf - .env secrets inputs |
  limactl shell --workdir=/ kakaotalk-test sudo tar --no-same-owner -xf - -C /srv/kakaotalk-collector
```

Mac and VM UIDs differ, so `--no-same-owner` makes the copied files owned by root in the VM. Preserve the 0700 permissions on `secrets/`.

Transfer the images as well. These are the default tags; use your configured names if you changed them in `.env`.

```bash
docker save kakaotalk-collector/device:0.1.0 kakaotalk-collector/server:0.1.0 |
  gzip -1 | limactl shell --workdir=/ kakaotalk-test sudo docker load
```

## 3. Start and sign in

```bash
./scripts/lima-compose.sh up -d --no-build
./scripts/lima-compose.sh ps
./scripts/lima-compose.sh exec -T admin python -m device.cli probe
```

Trust the verified public certificate `secrets/tls_cert.pem` copied to the VM earlier. For a one-time browser pairing code on this manual deployment, run:

```bash
./scripts/lima-compose.sh exec -T admin python -m webui.auth pair
```

Open `https://localhost:18443/admin/#pair=<code>` with the printed code, set an admin password on the first visit, and follow the [login procedure](web-ui.md#first-login). The code expires after ten minutes; do not share it. The admin recovery key remains an alternative. `./bridge admin` on the Mac targets the new installer's managed VM, so use the command above for `kakaotalk-test`.

`lima-compose.sh` runs Compose in `/srv/kakaotalk-collector` inside the VM. Running plain `docker ps` on the Mac shows Docker Desktop's state instead.

## Stop and restart

```bash
limactl stop kakaotalk-test
limactl start kakaotalk-test
./scripts/lima-compose.sh up -d --no-build
```

Stopping preserves volumes. `limactl delete` and `docker compose down -v` are not routine shutdown commands. If MCP is also running, add `--profile dot` to the restart command.

## Differences from the Linux defaults

`deploy/compose.lima.yaml` pins an Android 14 image by digest that runs on Apple Silicon and supports 64-bit apps only. It bind-mounts binderfs inodes directly at `/dev/binder`, `/dev/hwbinder`, and `/dev/vndbinder`. A systemd service in the VM prepares the devices at boot.

Android boot, secondary login, and Iris collection of new messages have been verified in this environment. See [Validation scope](implementation.md). For continuous operation, manage power, network, and sleep settings: Mac sleep can interrupt external access and collection.
