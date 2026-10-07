"""Remove what this installation created; shared tools such as Docker, Lima and Tailscale stay."""

import hashlib
import json
import platform
import re
import shutil
import sys
from pathlib import Path

from ops import cli, expose, launcher
from ops.errors import BridgeError

SYSTEMD = Path("/etc/systemd/system")
# Written by onboarding.prepare_linux; removed only while they still hold exactly that.
BINDER_CONFIG = {
    Path("/etc/modules-load.d/kakaotalk-bridge.conf"): "binder_linux\n",
    Path(
        "/etc/modprobe.d/kakaotalk-bridge.conf"
    ): "options binder_linux devices=binder,hwbinder,vndbinder\n",
}
# Install-folder state; a Git checkout keeps its source code.
STATE = (".env", "secrets", ".bridge", "backups", "inputs", "artifacts")
IMAGE_PREFIXES = ("ghcr.io/rokrokss/kakaotalk-bridge-", "kakaotalk-bridge/")
IMAGES = {"redroid/redroid", "ghcr.io/openai/tunnel-client"}


def confirm(args, mac):
    print("다음을 삭제합니다. 되돌릴 수 없습니다.")
    config = cli.ROOT / ".bridge/mac.json"
    if not mac:
        print("- 컨테이너, 볼륨(카카오톡 로그인, 수집한 메시지, 패스키), 이미지, 웹 연결 설정 서비스")
    elif config.exists():
        vm = json.loads(config.read_text())["vm"]
        print(f"- Lima VM({vm})과 그 안의 서비스, 카카오톡 로그인, 수집한 메시지, 패스키, 백업")
    if (cli.ROOT / ".git").exists():
        print("- 설치 폴더의 설정, 키, 백업 (소스 코드는 유지)")
    else:
        print(f"- 설치 폴더 전체: {cli.ROOT}")
    if launcher.serves_this():
        print(f"- {launcher.path()} 명령")
    print("Docker, Lima, Tailscale 같은 공용 도구는 지우지 않습니다.")
    if args.yes:
        return
    if not sys.stdin.isatty():
        raise BridgeError("입력할 수 없는 환경에서는 --yes를 함께 지정하세요.")
    if input("계속하려면 '삭제'를 입력하세요: ").strip() != "삭제":
        print("취소했습니다. 아무것도 지우지 않았습니다.")
        raise SystemExit(1)


def remove_funnel():
    """Turn off Tailscale Funnel only while it still serves exactly what kakaotalk-bridge expose set."""
    record = cli.ROOT / ".bridge/expose.json"
    tailscale = expose.tailscale_binary()
    if not record.exists() or not tailscale:
        return
    try:
        current = json.loads(cli.run([tailscale, "serve", "status", "--json"], capture=True))
    except RuntimeError:
        cli.notice("Tailscale 상태를 확인하지 못해 공개 설정은 그대로 두었습니다.")
        return
    if not current:
        return
    if current != json.loads(record.read_text()).get("config"):
        cli.notice("Tailscale에 Bridge가 만들지 않은 공개 설정이 있어 그대로 두었습니다.")
        return
    cli.run([tailscale, "serve", "reset"], capture=True)


def remove_vm():
    config = cli.ROOT / ".bridge/mac.json"
    if not config.exists():
        return
    if not shutil.which("limactl"):
        raise BridgeError("Lima를 찾을 수 없어 VM을 지우지 못했습니다. brew install lima로 설치한 뒤 다시 실행하세요.")
    vm = json.loads(config.read_text())["vm"]
    if vm in cli.run(["limactl", "list", "--format", "{{.Name}}"], capture=True).splitlines():
        cli.progress("가상 머신 삭제 중…")
        cli.run(["limactl", "delete", "--force", vm], capture=True)


def remove_setup_service():
    # Same name as setup_agent.install gives this installation's unit.
    unit = "kakaotalk-setup-" + hashlib.sha256(str(cli.ROOT).encode()).hexdigest()[:12] + ".service"
    if not (SYSTEMD / unit).exists():
        return
    cli.run(["systemctl", "disable", "--now", unit], capture=True)
    (SYSTEMD / unit).unlink()
    cli.run(["systemctl", "daemon-reload"], capture=True)


def remove_docker():
    if not shutil.which("docker"):
        return
    project = cli.read_env().get("COMPOSE_PROJECT_NAME", "kakaotalk-bridge")
    label = "label=com.docker.compose.project=" + project
    cli.progress("컨테이너와 데이터 삭제 중…")
    containers = cli.run(["docker", "ps", "-aq", "--filter", label], capture=True).split()
    if containers:
        cli.run(["docker", "rm", "-f", *containers], capture=True)
    # Restored volumes are external to Compose, so select them by name, not by label.
    volumes = [
        name
        for name in cli.run(["docker", "volume", "ls", "-q"], capture=True).split()
        if name.startswith(project + "_") or re.fullmatch(r"restore-[0-9a-f]{12}-scratch", name)
    ]
    if volumes:
        cli.run(["docker", "volume", "rm", *volumes], capture=True)
    networks = cli.run(["docker", "network", "ls", "-q", "--filter", label], capture=True).split()
    if networks:
        cli.run(["docker", "network", "rm", *networks], capture=True)
    cli.progress("이미지 삭제 중…")
    kept = []
    listing = cli.run(
        ["docker", "image", "ls", "--digests", "--format", "{{.Repository}} {{.Tag}} {{.Digest}}"],
        capture=True,
    )
    for line in listing.splitlines():
        repository, tag, digest = line.split()
        if repository in IMAGES or repository.startswith(IMAGE_PREFIXES):
            # Release images are pulled by digest and have no tag.
            image = f"{repository}:{tag}" if tag != "<none>" else f"{repository}@{digest}"
            try:
                cli.run(["docker", "image", "rm", image], capture=True)
            except RuntimeError:
                kept.append(image)
    if kept:
        cli.notice("다른 컨테이너가 사용 중인 이미지는 남겨 두었습니다: " + ", ".join(kept))


def remove_binder_config():
    for path, content in BINDER_CONFIG.items():
        if path.is_file() and path.read_text() == content:
            path.unlink()


def remove_files():
    if (cli.ROOT / ".git").exists():
        for name in STATE:
            path = cli.ROOT / name
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
    else:
        shutil.rmtree(cli.ROOT)


def cleanup(args):
    mac = platform.system() == "Darwin" and not args.local
    confirm(args, mac)
    remove_funnel()
    if mac:
        remove_vm()
    else:
        remove_setup_service()
        remove_docker()
        remove_binder_config()
    launcher.remove()
    # Last: the folder records the project, VM and Funnel a rerun needs, and an error
    # after this would recreate .bridge/logs and block a fresh install here.
    remove_files()
    print(
        "KakaoTalk Bridge를 삭제했습니다.\n"
        "Docker, Lima, Tailscale, uv 같은 공용 도구와 셸 설정은 그대로 있습니다. "
        "AI 앱에 추가한 연결과 Tailscale 관리 콘솔의 기기는 직접 지우세요."
    )
