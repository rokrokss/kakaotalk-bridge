"""Admin screen links, passkey setup and public HTTPS addresses."""

import json
import platform
import re
import webbrowser
from urllib.parse import urlsplit

from ops import cli, install
from ops.errors import BridgeError


def admin_code():
    return cli.compose("exec", "-T", "admin", "python", "-m", "webui.auth", "pair", capture=True)


def admin_info():
    return json.loads(
        cli.compose("exec", "-T", "admin", "python", "-m", "webui.auth", "info", capture=True)
    )


def admin_url(override=None):
    if override:
        return private_url(override)
    path = cli.ROOT / ".bridge/admin-url"
    if path.exists():
        return private_url(path.read_text().strip())
    if platform.system() == "Darwin":
        path = cli.ROOT / ".bridge/mac.json"
        port = (
            str(json.loads(path.read_text()).get("local_admin_port", 18789))
            if path.exists()
            else "18789"
        )
    else:
        port = cli.read_env().get("ADMIN_LOCAL_PORT", "18789")
    return private_url("http://localhost:" + port)


def open_admin_page(url):
    url = private_url(url)
    print("관리 화면: " + url + "\n설정한 방식으로 로그인하세요.")
    webbrowser.open(url)


def passkey_setup(args):
    if platform.system() == "Darwin" and not args.local:
        config = json.loads((cli.ROOT / ".bridge/mac.json").read_text())
        command = [
            "limactl",
            "shell",
            "--workdir=/",
            config["vm"],
            "sudo",
            config["directory"] + "/bridge",
            "--local",
            "passkey-login",
            "--link-only",
        ]
        saved_origin = cli.ROOT / ".bridge/admin-url"
        if args.url or saved_origin.exists():
            command += ["--url", args.url or saved_origin.read_text().strip()]
        elif config.get("local_admin_port"):
            command += ["--url", "http://localhost:" + str(config["local_admin_port"])]
        if args.public_url:
            command += ["--public-url", args.public_url]
        if args.enroll:
            command += ["--enroll"]
        link = cli.run(command, capture=True)
        cli.atomic(saved_origin, private_url(link.partition("#")[0]))
    else:
        # A new limited verifier credential can be added without rotating existing identities.
        install.ensure_passkey_verifier_secret()
        install.migrate_auth_modes()
        cli.compose("up", "-d", "--no-build", "--no-deps", "dot-control", capture=True)

        def helper(operation, payload=None):
            return cli.compose(
                "exec",
                "-T",
                "dot-control",
                "python",
                "-m",
                "server.passkeys",
                operation,
                input=payload,
                capture=True,
            )

        info = json.loads(helper("info"))
        saved_origin = cli.ROOT / ".bridge/admin-url"
        origin = private_url(
            args.url
            or (saved_origin.read_text().strip() if saved_origin.exists() else None)
            or info.get("admin_origin")
            or admin_url()
        ).removesuffix("/admin/")
        public = args.public_url or cli.read_env().get("DOT_PUBLIC_URL", "")
        if public.endswith(".invalid"):
            public = ""
        if public:
            validate_public_url(public)
            if public != cli.read_env().get("DOT_PUBLIC_URL"):
                raise BridgeError("먼저 ./bridge connect --url <공개 주소>로 공개 HTTPS 주소를 설정하세요.")
        # A localhost passkey cannot authenticate a different public RP. Keep
        # the admin identity and use the existing code-confirmation consent flow.
        passkey_public = (
            public
            if (
                origin.startswith("https://")
                and urlsplit(origin).hostname == urlsplit(public).hostname
            )
            else ""
        )
        if (
            not info["configured"]
            or info["admin_origin"] != origin
            or info["public_origin"] != passkey_public
        ):
            helper(
                "configure", json.dumps({"admin_origin": origin, "public_origin": passkey_public})
            )
        updates = {"ADMIN_AUTH_MODE": "passkey"}
        if public:
            updates["DOT_APPROVAL_MODE"] = "passkey" if passkey_public else "admin"
        if origin.startswith("http://localhost:"):
            updates.update(
                {"ADMIN_LOCAL_ORIGIN": origin, "ADMIN_LOCAL_HOST": urlsplit(origin).netloc}
            )
        cli.env_update(updates)
        cli.atomic(cli.ROOT / ".bridge/admin-url", private_url(origin))
        cli.compose(
            "up",
            "-d",
            "--no-build",
            "--no-deps",
            "--wait",
            "--wait-timeout",
            "60",
            "admin",
            *(["admin-local"] if origin.startswith("http://localhost:") else []),
            *(["dot-plugin", "dot-control", "dot-ingress"] if public else []),
            capture=True,
        )
        link = private_url(origin)
        if args.enroll or not info["registered"]:
            token = helper("enroll")
            if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
                raise BridgeError("패스키 등록 응답이 올바르지 않습니다. 잠시 후 다시 시도하세요.")
            link += "#passkey-setup=" + token
    if args.link_only:
        print(link)
    else:
        print("아래 설정 링크를 여세요 (등록 링크는 10분 후 만료):\n" + link)
        webbrowser.open(link)


def private_url(value):
    parsed = urlsplit(value)
    if (
        not (
            parsed.scheme == "https"
            or (
                parsed.scheme == "http"
                and parsed.netloc == f"localhost:{parsed.port}"
                and parsed.port is not None
                and 1024 <= parsed.port <= 65535
            )
        )
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/admin/")
    ):
        raise BridgeError("관리 화면 주소는 HTTPS 주소 또는 http://localhost:<포트> 형식으로, ? 뒤 값 없이 입력하세요.")
    return value.rstrip("/").removesuffix("/admin") + "/admin/"


def open_admin(code, url):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", code):
        raise BridgeError("관리 화면 연결 응답이 올바르지 않습니다. 잠시 후 다시 시도하세요.")
    link = private_url(url) + "#pair=" + code
    print("일회용 관리 화면 링크 (10분 후 만료):\n" + link)
    webbrowser.open(link)


def validate_public_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.hostname.endswith(".invalid")
    ):
        raise BridgeError("공개 HTTPS 주소를 끝에 /를 붙이지 않고 입력하세요. 예: https://bridge.example.com")


def connect(url):
    validate_public_url(url)
    mode = cli.read_env().get("DOT_APPROVAL_MODE", "passkey")
    cli.env_update({"DOT_PUBLIC_URL": url, "DOT_APPROVAL_MODE": mode})
    cli.atomic(cli.ROOT / ".bridge/public-url", url)
    cli.compose("up", "-d", "--no-build", "dot-plugin", "dot-control", "dot-ingress")
    print(url + "/mcp\n./bridge passkey-login으로 이 주소의 로그인을 설정하세요.")
