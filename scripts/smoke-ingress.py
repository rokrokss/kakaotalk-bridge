"""Exercise the shared Caddy ingress with synthetic admin and MCP upstreams.

Requires locally built server and gateway images. No production volumes or ports
are used. Override SMOKE_SERVER_IMAGE / SMOKE_GATEWAY_IMAGE when testing a release.
"""

import http.client
import json
import os
import subprocess
import uuid
from pathlib import Path


def main():
    suffix = uuid.uuid4().hex[:12]
    network = f"kakao-ingress-test-{suffix}"
    edge = f"{network}-edge"
    upstream = f"{network}-echo"
    admin = f"{network}-admin"
    ingress = f"{network}-proxy"
    server = os.getenv("SMOKE_SERVER_IMAGE", "kakaotalk-collector/server:0.1.0")
    gateway = os.getenv("SMOKE_GATEWAY_IMAGE", "kakaotalk-collector/gateway:2.11.7")
    config = Path(__file__).resolve().parents[1] / "docker/Caddyfile.public"

    def run(*args):
        return subprocess.run(["docker", *args], text=True, capture_output=True, check=True).stdout

    echo = """
from http.server import BaseHTTPRequestHandler, HTTPServer
import json, sys
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Set-Cookie', '__Host-kakao-link=consent-test; Secure; Path=/; HttpOnly')
        for name in ['__Host-kakao-admin', '__Secure-kakao-admin-v2', '__Host-passkey-admin-flow']:
            self.send_header('Set-Cookie', name+'=private-test; Secure; Path=/admin; HttpOnly')
        self.end_headers()
        self.wfile.write(json.dumps(self.headers.get_all('Cookie', [])).encode())
    def log_message(self, *args): pass
HTTPServer(('0.0.0.0', int(sys.argv[1])), Handler).serve_forever()
"""
    probe = """
import http.client, json, time
def request(path, cookies):
    c = http.client.HTTPConnection('ingress', 8786, timeout=3)
    try:
        c.putrequest('GET', path)
        for value in cookies: c.putheader('Cookie', value)
        c.endheaders()
        r = c.getresponse()
        headers = r.getheaders()
        for key, value in headers:
            if key.lower() == 'set-cookie' and not path.startswith('/admin/'):
                assert 'private-test' not in value, headers
        if r.status == 200:
            assert any(key.lower() == 'set-cookie' and value.startswith('__Host-kakao-link=')
                       for key, value in headers), headers
        return r.status, r.read()
    finally: c.close()
for _ in range(40):
    try:
        if request('/mcp', [])[0] == 200: break
    except OSError: pass
    time.sleep(.25)
else: raise AssertionError('ingress did not become ready')
private = ['__Host-kakao-admin', '__Secure-kakao-admin-v2', '__Host-passkey-admin-flow']
keep = '__Host-kakao-link=consent-test'
cases = [[keep], [], ['; '.join(n + '=private-test' for n in private) + '; ' + keep]]
for name in private:
    for value in [name+'=private-test; '+keep, keep+'; '+name+'=private-test',
                  'other=ok;'+name+'=private-test;'+keep]:
        cases.append([value])
    cases.append([name+'=private-test', keep, name+'=private-test'])
for cookies in cases:
    status, body = request('/authorize', cookies)
    assert status == 200
    values = json.loads(body)
    assert all('private-test' not in value for value in values), cookies
    if cookies: assert keep in ';'.join(values), cookies
for path in ['/passkeys/admin', '/passkeys/admin/credentials', '/internal', '/internal/v1/test', '/v1/messages']:
    assert request(path, [keep])[0] == 404, path
for path in ['/', '/admin']:
    assert request(path, [])[0] == 302, path
for path in ['/admin/', '/admin/api/session']:
    status, body = request(path, ['__Secure-kakao-admin-v2=private-test'])
    assert status == 200, path
    assert 'private-test' in ';'.join(json.loads(body)), path
print(f'PASS: {len(cases)} cookie cases, including duplicate headers; OAuth cookie retained')
print('PASS: admin and MCP share one port; admin cookies reach only admin')
print('PASS: root/admin redirects and 5 internal paths rejected before upstream')
print('PASS: private Set-Cookie values suppressed; OAuth Set-Cookie retained')
"""
    try:
        run("network", "create", "--internal", network)
        run("network", "create", edge)
        run(
            "run",
            "-d",
            "--name",
            upstream,
            "--network",
            network,
            "--network-alias",
            "dot-plugin",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--entrypoint",
            "python",
            server,
            "-c",
            echo,
            "8787",
        )
        run(
            "run",
            "-d",
            "--name",
            admin,
            "--network",
            network,
            "--network-alias",
            "admin",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--entrypoint",
            "python",
            server,
            "-c",
            echo,
            "8080",
        )
        run(
            "run",
            "-d",
            "--name",
            ingress,
            "--network",
            network,
            "--network",
            edge,
            "-p",
            "127.0.0.1::8786",
            "--network-alias",
            "ingress",
            "--user",
            "10001:10001",
            "--read-only",
            "--tmpfs",
            "/tmp",
            "--tmpfs",
            "/data:uid=10001,gid=10001,mode=0700",
            "--tmpfs",
            "/config:uid=10001,gid=10001,mode=0700",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "-v",
            f"{config}:/etc/caddy/Caddyfile:ro",
            gateway,
        )
        print(
            run(
                "run",
                "--rm",
                "--network",
                network,
                "--read-only",
                "--tmpfs",
                "/tmp",
                "--cap-drop",
                "ALL",
                "--entrypoint",
                "python",
                server,
                "-c",
                probe,
            ),
            end="",
        )
        published = json.loads(run("inspect", ingress))[0]["NetworkSettings"]["Ports"]["8786/tcp"]
        assert len(published) == 1 and published[0]["HostIp"] == "127.0.0.1"
        connection = http.client.HTTPConnection(
            "127.0.0.1", int(published[0]["HostPort"]), timeout=5
        )
        try:
            connection.request(
                "GET",
                "/health/live",
                headers={
                    "Cookie": "__Secure-kakao-admin-v2=private-test; __Host-kakao-link=consent-test"
                },
            )
            response = connection.getresponse()
            values = response.read().decode()
            assert (
                response.status == 200 and "private-test" not in values and "consent-test" in values
            )
        finally:
            connection.close()
        print("PASS: published host-loopback port works and filters cookies")
    finally:
        for name in [ingress, upstream, admin]:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
        subprocess.run(["docker", "network", "rm", network], capture_output=True, check=False)
        subprocess.run(["docker", "network", "rm", edge], capture_output=True, check=False)


if __name__ == "__main__":
    main()
