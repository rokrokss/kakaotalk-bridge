#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
umask 077
mkdir -p secrets inputs/kakao artifacts backups
chmod 700 secrets backups
for name in admin_token ingest_token read_token device_token bridge_key_password backup_key mcp_approval_token mcp_passkey_token; do
    if [[ ! -s "secrets/$name" ]]; then openssl rand -hex 32 > "secrets/$name"; fi
done
# Parent directory is 0700; mounted runtime files must be readable by container UID 10001.
chmod 444 secrets/admin_token secrets/ingest_token secrets/read_token secrets/device_token secrets/backup_key secrets/mcp_approval_token secrets/mcp_passkey_token
if [[ -e secrets/tls_cert.pem || -e secrets/tls_key.pem ]]; then
    [[ -s secrets/tls_cert.pem && -s secrets/tls_key.pem ]] || { echo 'Incomplete TLS pair; restore it.' >&2; exit 1; }
else
    openssl req -x509 -newkey rsa:3072 -nodes -days 365 -sha256 \
        -keyout secrets/tls_key.pem -out secrets/tls_cert.pem \
        -subj '/CN=KakaoTalk Bridge Private Gateway' \
        -addext "subjectAltName=IP:${GATEWAY_IP:-172.29.87.3},IP:127.0.0.1,DNS:localhost" >/dev/null 2>&1
fi
chmod 444 secrets/tls_cert.pem secrets/tls_key.pem
if [[ ! -s secrets/bridge.jks && "${BRIDGE_PREBUILT:-0}" != 1 ]]; then
    docker run --rm --user 0 --entrypoint keytool \
        -v "$PWD/secrets:/signing" \
        gradle:8.11.1-jdk17@sha256:91d559b8d55f522de5bc6882f73bcedc4e2cc7b0a58e839a9fa0ed95811a988d \
        -genkeypair -alias bridge -keyalg RSA -keysize 3072 -validity 3650 \
        -dname 'CN=Personal Notification Bridge' -keystore /signing/bridge.jks \
        -storepass:file /signing/bridge_key_password -keypass:file /signing/bridge_key_password
fi
echo 'Secrets ready; existing keys were preserved. Back up secrets/ securely.'
