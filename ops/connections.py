"""Choose an optional AI connection without replacing the admin identity."""

import argparse
import getpass
import json
import sys
import tempfile
from pathlib import Path

from ops import cli, onboarding, tunnel

METHODS = ("none", "stdio", "https", "tailscale", "openai-tunnel")


def add_arguments(parser):
    parser.add_argument("--method", choices=METHODS)
    parser.add_argument("--url", help="Public HTTPS MCP origin; keeps your admin address")
    parser.add_argument("--tunnel-id")
    parser.add_argument("--api-key-file")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-install", action="store_true")


def ask(prompt):
    if not sys.stdin.isatty():
        raise ValueError("Use --method and its required options when running non-interactively")
    return input(prompt).strip()


def setup(args):
    method = args.method
    if method is None:
        print(
            "AI connections are optional and can coexist. Existing connections are kept.\n"
            "1. Later (keep current setup)\n"
            "2. Local AI client — stdio\n"
            "3. Public HTTPS — your reverse proxy + OAuth\n"
            "4. Public HTTPS — Tailscale Funnel + OAuth\n"
            "5. ChatGPT — personal OpenAI tunnel"
        )
        choice = ask("Choose [1]: ") or "1"
        if choice not in {"1", "2", "3", "4", "5"}:
            raise ValueError("Choose a number from 1 to 5")
        method = METHODS[int(choice) - 1]
    if args.url and method != "https":
        raise ValueError("--url requires --method https")
    if (args.tunnel_id or args.api_key_file) and method != "openai-tunnel":
        raise ValueError("Tunnel credentials require --method openai-tunnel")
    if method == "none":
        print("No connection changes. Collection and admin work without an AI connection.")
        return
    if method == "stdio":
        print("Add this server to your local AI client's MCP configuration:")
        print(
            json.dumps(
                {
                    "mcpServers": {
                        "kakaotalk": {
                            "command": sys.executable,
                            "args": [str(cli.ROOT / "bridge"), "mcp"],
                        }
                    }
                },
                indent=2,
            )
        )
        print(
            "The client must have access to this installation's Docker Engine or managed Lima VM.\n"
            "For a remote server, invoke the same bridge mcp command through SSH (without a TTY)."
        )
        return
    with tempfile.TemporaryDirectory(prefix="bridge-connection-") as folder:
        if method == "https":
            args.url = args.url or ask("Public HTTPS origin (https://your-host): ")
            cli.validate_public_url(args.url)
        if method == "openai-tunnel":
            print(
                "Use the tunnel ID and runtime API key from your OpenAI workspace.\n"
                "Provider setup: https://developers.openai.com/api/docs/guides/secure-mcp-tunnels"
            )
            args.tunnel_id = args.tunnel_id or ask("Tunnel ID: ")
            if not args.api_key_file:
                if not sys.stdin.isatty():
                    raise ValueError("Supply --api-key-file when running non-interactively")
                path = Path(folder) / "runtime-key"
                cli.atomic(path, getpass.getpass("Runtime API key (hidden): ").strip() + "\n")
                args.api_key_file = str(path)
            tunnel.credentials(args.tunnel_id, args.api_key_file)
        options = argparse.Namespace(
            connection=method,
            admin_url=None,
            public_url=args.url,
            tunnel_id=args.tunnel_id,
            api_key_file=args.api_key_file,
            no_browser=args.no_browser,
            no_install=args.no_install,
        )
        with onboarding.installation_lock():
            runtime = onboarding.Runtime()
            if not runtime.installed():
                raise RuntimeError("Run ./bridge up before adding an AI connection")
            runtime.call("start")
            if method == "tailscale":
                prepare = (
                    onboarding.prepare_mac
                    if cli.platform.system() == "Darwin"
                    else onboarding.prepare_linux
                )
                prepare(options)
            onboarding.connect_network(options, runtime)
            # This configures OAuth consent automatically, retaining the existing
            # passkey RP. Tunnel consent still requires an explicit admin decision.
            onboarding.open_setup(options, runtime)
            if method in {"https", "tailscale"}:
                print(
                    "Add the public /mcp address in your AI client and select OAuth.\n"
                    "Follow the consent screen; if it shows a code, match it in admin → Connections."
                )
