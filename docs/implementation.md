# Validation scope

[Development and test commands](development.md) · [Current architecture](design.md)

## Verified with a real account

On 2026-10-04, using Lima/Ubuntu 24.04 arm64 on an Apple Silicon Mac:

- redroid boot with Android 14, SM-T970 tablet configuration, and 1200 × 1920 resolution at density 240.
- Screen viewing, control, and Korean text input through the web admin console.
- KakaoTalk secondary-device option check (“다른 기기와 함께 사용”, meaning “Use with other devices”) and secondary login.
- Phone session continuity, manually confirmed by the user on the phone; this was not an automated server check.
- Iris database row storage and collection of new messages sent to self after approval.
- State volume persistence across container and VM restarts.
- Public HTTPS OAuth flow and successful connection of `KakaoTalk Bridge` in ChatGPT.

## Automated checks

Python tests use synthetic data to cover authentication, CSRF, Origin, login approval conditions, database deduplication, cursors, restores, MCP queries, and event retries, revocation, and expiry. Docker smoke tests cover the API, gateway, stdio MCP, SQLite, and encrypted backups.

Image builds and API startup have been verified on amd64. This does not establish redroid or KakaoTalk compatibility on an amd64 host. Reproduction commands are in [Development](development.md).

## Not yet verified

Compatibility with other KakaoTalk versions and hosts, completeness of conversation history, end-to-end comparison of read status before and after collection, and 24–72 hours of continuous reception require further validation. Actual Dot event execution has not been verified, and automatic subscription is not a requirement.

Details of the initial notification-based MVP and troubleshooting history remain in Git. Refer to [Iris](iris.md), [Admin console](web-ui.md), and [MCP](dot-plugin.md) for current behavior.
