"""Encrypted full snapshots of Android, collector data and configuration."""

import contextlib
import json
import os
import secrets
import subprocess
import time
from pathlib import Path

from ops import cli
from ops.errors import BridgeError


def volume_names():
    config = json.loads(cli.compose("config", "--format", "json", capture=True))
    return {name: config["volumes"][name]["name"] for name in cli.VOLUMES}


def snapshot_command(mode, names, *, key=None, stage=None, work=None, image=None):
    env = cli.read_env()
    image = (
        image
        or env.get("DOT_IMAGE")
        or env.get("COLLECTOR_IMAGE", "kakaotalk-bridge/server:local")
    )
    cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--user",
        "0",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "DAC_OVERRIDE",
        "--cap-add",
        "CHOWN",
        "--cap-add",
        "FOWNER",
        "--cap-add",
        "SETFCAP",
        "--security-opt",
        "no-new-privileges:true",
        "--entrypoint",
        "python",
    ]
    for name, volume in names.items():
        cmd += ["-v", f"{volume}:/snapshot/{name}" + (":ro" if mode == "create" else "")]
    key_path = str(key or cli.ROOT / "secrets/backup_key")
    project_path = str(stage or cli.ROOT)
    if any(c in key_path + project_path for c in ",:\r\n"):
        raise BridgeError("설치 경로에 쉼표, 콜론, 줄바꿈이 들어갈 수 없습니다. 다른 위치에 설치하세요.")
    cmd += ["--mount", f"type=bind,src={key_path},dst=/key,readonly"]
    cmd += ["-v", f"{stage or cli.ROOT}:/project" + (":ro" if mode == "create" else "")]
    if work:
        cmd += [
            "-v",
            f"{work}:/work",
            "-e",
            f"RESTORE_UID={os.getuid()}",
            "-e",
            f"RESTORE_GID={os.getgid()}",
        ]
    cmd += [image, "-m", "ops.snapshot", mode]
    return cmd


def backup(helper_image=None, name=None):
    root = cli.ROOT / "backups"
    root.mkdir(mode=0o700, exist_ok=True)
    destination = root / (
        name or (time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3) + ".kcs")
    )
    names = volume_names()
    existing = set(
        cli.run(["docker", "volume", "ls", "--format", "{{.Name}}"], capture=True).splitlines()
    )
    names = {name: value for name, value in names.items() if value in existing}
    running = cli.compose("ps", "--status", "running", "--services", capture=True).splitlines()
    cli.progress("백업을 위해 서비스를 잠시 멈추는 중…")
    cli.compose("stop")
    try:
        cli.progress("암호화 백업 만드는 중…")
        with destination.open("xb") as output:
            destination.chmod(0o600)
            result = subprocess.run(
                snapshot_command("create", names, image=helper_image),
                cwd=cli.ROOT,
                stdout=output,
                stderr=cli.diagnostics(),
                check=False,
            )
        if result.returncode:
            destination.unlink(missing_ok=True)
            raise BridgeError("백업을 만들지 못했습니다. 일부만 만들어진 파일은 삭제했습니다.")
    finally:
        if running:
            cli.progress("서비스 다시 시작 중…")
            cli.compose("start", *running)
    cli.notice(f"암호화된 백업: {destination}\n복구에 필요한 secrets/backup_key는 별도로 보관하세요.")
    return destination


def recover_activation():
    journal = cli.ROOT / ".bridge/restore-activation.json"
    if not journal.exists():
        return
    record = json.loads(journal.read_text())
    stage = Path(record["stage"])
    for item in (".env", "secrets"):
        previous = stage / (item.replace(".", "") + "-previous")
        if previous.exists():
            if (cli.ROOT / item).exists():
                (cli.ROOT / item).rename(stage / item)
            previous.rename(cli.ROOT / item)
    override = cli.ROOT / ".bridge/volumes.yaml"
    if record["volumes"] is None:
        override.unlink(missing_ok=True)
    else:
        cli.atomic(override, record["volumes"])
    journal.unlink()


def activate_restore(stage, names):
    for item in ("secrets", ".env"):
        if not (stage / item).exists() or not (cli.ROOT / item).exists():
            raise BridgeError("백업 또는 설치가 완전하지 않아 기존 설정을 유지했습니다.")
    override = cli.ROOT / ".bridge/volumes.yaml"
    journal = cli.ROOT / ".bridge/restore-activation.json"
    cli.atomic(
        journal,
        json.dumps(
            {"stage": str(stage), "volumes": override.read_text() if override.exists() else None}
        ),
    )
    try:
        for item in ("secrets", ".env"):
            (cli.ROOT / item).rename(stage / (item.replace(".", "") + "-previous"))
            (stage / item).rename(cli.ROOT / item)
        content = "volumes:\n" + "".join(
            f"  {name}:\n    name: {value}\n    external: true\n" for name, value in names.items()
        )
        cli.atomic(override, content)
        cli.atomic(cli.ROOT / ".bridge/restored-pending", "1\n")
        journal.unlink()
    except BaseException:
        recover_activation()
        raise


def restore(path, key):
    archive, key = Path(path).resolve(), Path(key).resolve()
    if not archive.is_file() or not key.is_file():
        raise BridgeError("백업 파일과 복구 키 파일을 모두 지정하세요.")
    if cli.compose("ps", "--status", "running", "--services", capture=True):
        raise BridgeError("복구하기 전에 ./bridge stop으로 서비스를 중지하세요. 기존 데이터는 보존됩니다.")
    suffix = "restore-" + secrets.token_hex(6)
    names = {
        name: cli.read_env().get("COMPOSE_PROJECT_NAME", "kakaotalk-bridge")
        + "_"
        + suffix
        + "_"
        + name
        for name in cli.VOLUMES
    }
    stage = cli.ROOT / ".bridge" / suffix
    stage.mkdir(mode=0o700, parents=True)
    work = suffix + "-scratch"
    for name in [*names.values(), work]:
        cli.run(["docker", "volume", "create", name], capture=True)
    try:
        cli.progress("백업을 검증하고 새 저장소로 복구하는 중…")
        with archive.open("rb") as source:
            result = subprocess.run(
                snapshot_command("restore", names, key=key, stage=stage, work=work),
                cwd=cli.ROOT,
                stdin=source,
                stdout=cli.diagnostics(),
                stderr=cli.diagnostics(),
                check=False,
            )
        if result.returncode:
            raise BridgeError("복구한 데이터 검증에 실패했습니다. 복구 키와 백업 파일을 확인하세요. 기존 데이터와 키는 바꾸지 않았습니다.")
        activate_restore(stage, names)
        restored = cli.read_env()
        if restored.get("OPENAI_TUNNEL_ENABLED") == "1":
            cli.atomic(
                cli.ROOT / ".bridge/tunnel.json",
                json.dumps({"tunnel_id": restored["OPENAI_TUNNEL_ID"]}),
            )
        else:
            (cli.ROOT / ".bridge/tunnel.json").unlink(missing_ok=True)
        cli.notice(
            "새 볼륨으로 복구했습니다. 이전 볼륨과 설정은 유지됩니다. ./bridge start를 실행하고 두 기기의 로그인을 확인하세요. 외부 이벤트 구독은 다시 만들어야 합니다."
        )
    finally:
        with contextlib.suppress(RuntimeError, OSError):
            cli.run(["docker", "volume", "rm", work], capture=True)
