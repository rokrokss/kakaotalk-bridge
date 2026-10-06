"""Health report for the host, Docker services and credentials."""

import json
from datetime import UTC, datetime
from pathlib import Path

from ops import cli


def doctor(report=True):
    reports = {}
    for name, args in (
        ("docker", ["docker", "info", "--format", "{{.OSType}}/{{.Architecture}}"]),
        ("compose", ["docker", "compose", "version", "--short"]),
    ):
        try:
            reports[name] = {"ok": True, "version": cli.run(args, capture=True)}
        except (RuntimeError, OSError):
            reports[name] = {"ok": False}
    reports["binder"] = {
        "ok": Path("/sys/module/binder_linux").exists()
        or Path("/dev/binderfs/binder-control").exists()
    }
    try:
        raw = cli.compose("ps", "--all", "--format", "json", capture=True)
        rows = (
            json.loads(raw)
            if raw.startswith("[")
            else [json.loads(line) for line in raw.splitlines()]
        )
        reports["services"] = [
            {k: row.get(k, "") for k in ("Service", "State", "Health")} for row in rows
        ]
    except (RuntimeError, ValueError):
        reports["services"] = []
    reports["missing_secrets"] = [
        name
        for name in (
            "admin_token",
            "ingest_token",
            "read_token",
            "device_token",
            "backup_key",
            "mcp_storage_key",
            "mcp_approval_token",
            "tls_cert.pem",
            "tls_key.pem",
        )
        if not (cli.ROOT / "secrets" / name).is_file()
    ]
    reports["certificate"] = certificate()
    if cli.read_env().get("OPENAI_TUNNEL_ENABLED") == "1":
        from ops.tunnel import status

        reports["tunnel"] = status()
        reports["missing_secrets"] += [
            name
            for name in ("openai_tunnel_api_key", "mcp_tunnel_authorization")
            if not (cli.ROOT / "secrets" / name).is_file()
        ]
    expected = set(cli.services())
    healthy = {
        row["Service"]
        for row in reports["services"]
        if row["State"] == "running" and row["Health"] in ("", "healthy")
    }
    ok = (
        all(reports[name]["ok"] for name in ("docker", "compose", "binder", "certificate"))
        and not reports["missing_secrets"]
        and expected <= healthy
    )
    if report == "json":
        print(json.dumps(reports, indent=2))
    elif report:
        print(doctor_text(reports, expected, ok))
    return ok


def certificate():
    """Days left on the private HTTPS certificate; it is valid for a year and renewed by hand."""
    path = cli.ROOT / "secrets/tls_cert.pem"
    if not path.is_file():
        return {"ok": True, "days": None}
    try:
        end = cli.run(["openssl", "x509", "-enddate", "-noout", "-in", str(path)], capture=True)
        # OpenSSL prints the end date in GMT, e.g. "notAfter=Oct  6 12:00:00 2027 GMT".
        stamp = end.removeprefix("notAfter=").strip().removesuffix(" GMT") + " +0000"
        expires = datetime.strptime(stamp, "%b %d %H:%M:%S %Y %z")
    except (RuntimeError, OSError, ValueError):
        return {"ok": True, "days": None}
    days = (expires - datetime.now(UTC)).days
    return {"ok": days >= 0, "days": days, "expires": expires.date().isoformat()}


def doctor_text(reports, expected, ok):
    def line(label, good, detail=""):
        return f"  {label}: {'정상' if good else '확인 필요'}{f' ({detail})' if detail else ''}"

    def certificate_line(cert):
        if cert["days"] is None:
            return line("HTTPS 인증서", True, "만료일 확인 안 함")
        if cert["days"] < 0:
            return line(
                "HTTPS 인증서",
                False,
                f"{cert['expires']}에 만료됨, 운영 안내의 인증서 갱신을 따르세요",
            )
        if cert["days"] < 30:
            return f"  HTTPS 인증서: 곧 만료 ({cert['days']}일 남음, 운영 안내의 인증서 갱신을 따르세요)"
        return line("HTTPS 인증서", True, f"{cert['expires']}까지")

    states = {
        "running": "실행 중",
        "exited": "중지됨",
        "created": "시작 전",
        "restarting": "다시 시작 중",
    }
    lines = [
        "KakaoTalk Bridge 상태 점검",
        line("Docker", reports["docker"]["ok"], reports["docker"].get("version", "")),
        line("Docker Compose", reports["compose"]["ok"], reports["compose"].get("version", "")),
        line(
            "Android Binder",
            reports["binder"]["ok"],
            "" if reports["binder"]["ok"] else "Binder를 지원하는 커널이 필요합니다",
        ),
        line(
            "인증 키",
            not reports["missing_secrets"],
            "없음: " + ", ".join(reports["missing_secrets"]) if reports["missing_secrets"] else "",
        ),
        certificate_line(reports["certificate"]),
        "  서비스:",
    ]
    running = {row["Service"]: row for row in reports["services"]}
    for name in sorted(expected | set(running)):
        row = running.get(name)
        state = states.get(row["State"], row["State"]) if row else "없음"
        if row and name not in expected and row["State"] == "exited":
            state = "1회 실행 완료"
        health = {
            "healthy": ", 응답 정상",
            "unhealthy": ", 응답 없음",
            "starting": ", 시작 확인 중",
        }.get(row.get("Health", "") if row else "", "")
        lines.append(f"    {name}: {state}{health}")
    if "tunnel" in reports:
        lines.append(
            line(
                "개인 OpenAI 터널",
                reports["tunnel"]["ready"],
                "연결됨" if reports["tunnel"]["ready"] else "연결 대기",
            )
        )
    lines.append(
        "결과: "
        + (
            "모든 항목이 정상입니다."
            if ok
            else "확인이 필요한 항목이 있습니다. 위 내용을 확인하세요."
        )
    )
    return "\n".join(lines)
