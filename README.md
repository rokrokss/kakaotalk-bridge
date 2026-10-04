<div align="center">

<h1><img src="docs/assets/wordmark.svg?v=6b1a99c" width="450" height="96" alt="KakaoTalk Bridge"></h1>

**Connect your KakaoTalk messages to AI agents.**

KakaoTalk Bridge runs KakaoTalk headlessly on your server using redroid as a virtual Android tablet.<br>It collects messages from this secondary device and makes them available to AI agents through MCP.

[Get started](#getting-started) · [Connect your AI](#connect-your-ai) · [Documentation](#documentation) · [Contributing](CONTRIBUTING.md)

</div>

Iris reads the tablet's local message database and stores the collected messages on your server. Run the stack with Docker Compose, use the web admin console to install and sign in, then connect your AI client.

Use a [passkey](docs/passkeys.md) for admin and MCP connection approval. No developer account, client secret or separate authentication server is needed.

## See it in action

An illustrative conversation using synthetic messages:

```text
Collected messages
  “Friday meetup is at 7 PM.”
  “Friday meetup moved to 7:30 PM.”

You
  Find my collected messages mentioning "Friday" and summarize the plan.

Your AI
  Friday's meetup is now at 7:30 PM, updated from 7 PM.
```

The AI client searches through MCP and writes the summary from the retrieved messages. The bridge supplies the data. You can also ask it to retrieve recent collected messages or check collection status.

- **No physical tablet.** redroid runs the secondary Android device on your server.
- **Storage you control.** Messages are stored on your infrastructure, with a default 30-day retention period.
- **Read-only KakaoTalk access through MCP.** Agents can retrieve and search messages; no message-sending or tablet-control tools are exposed.

## Where does it run?

<p align="center">
  <img src="docs/assets/message-flow.svg" width="960" alt="Iris reads messages on a secondary tablet on your server and stores them locally. Your AI retrieves them through OAuth and MCP.">
</p>

Messages and the KakaoTalk session are stored in server volumes. Retrieved content is sent to your connected AI client. Admin access stays on private HTTPS; the remote MCP endpoint uses public HTTPS with OAuth. See [Architecture](docs/design.md) and [Security](docs/security.md).

Run Redroid in a dedicated VM. Its available official images have old Android security patches; authenticated ADB and service isolation reduce exposure but do not remove that [remaining risk](docs/security.md#dependency-results-and-remaining-android-risk).

## Getting started

1. **Set up your server.** Use the [installer](docs/onboarding.md) on Mac or Linux and register a [passkey](docs/passkeys.md) for admin and ChatGPT connections. Open the private admin URL and confirm with your device. The setup guide supports Aurora installation without a USB-connected phone.
2. **Sign in through the admin console.** Follow the [first login procedure](docs/web-ui.md#first-login). Select the secondary-device option and manually confirm that your phone's existing session remains active before starting collection.
3. **Connect your AI client.** Choose an [MCP connection method](#connect-your-ai) below.
4. **Try your first query.** Send yourself the two sample messages above from your phone, then ask your connected agent to find messages mentioning `Friday`. Confirm that both messages appear before asking for a summary.

> **Before signing in:** the login check currently recognizes the Korean KakaoTalk UI. Do not proceed if “Use with other devices” (“다른 기기와 함께 사용”) is missing or KakaoTalk asks to transfer the primary device. Phone sessions are not monitored automatically.

**Updating an existing server?** The security update requires one admin sign-in with your existing passkey. Registered passkeys and MCP connections are retained. Follow the [upgrade notes](docs/operations.md#upgrading-to-the-security-update) for the Iris migration and public proxy change.

## Connect your AI

| Connection | Setup | Validation |
| --- | --- | --- |
| Remote MCP over HTTPS with OAuth | [Server deployment and ChatGPT connection](docs/dot-plugin.md) | Passkey connection and profile/status calls verified; message retrieval confirmed by user testing. Event execution remains unverified |
| stdio MCP launched by your client | [Configuration example](docs/api.md#stdio-mcp) | Automated protocol tests; verify compatibility with your client |

[MCP Events](docs/events.md) are optional and require a separate subscription. Connecting a client does not create subscriptions or automated tasks.

## Requirements and validation

| Environment | Requirements | Validation |
| --- | --- | --- |
| Apple Silicon Mac | Lima Ubuntu VM; Docker Engine inside the VM | Secondary login and Iris collection verified end to end |
| Linux amd64 | Docker Engine, Compose v2, Android binder kernel support | Image builds and API startup verified; KakaoTalk/redroid flow unverified |
| Other Linux arm64 hosts | Docker Engine, Compose v2, Android binder kernel support | Not verified outside the Apple Silicon Lima setup |

The Linux guide suggests starting with 4 vCPUs and 8 GB RAM; these are not measured minimums. The supplied Lima VM uses 6 CPUs and 8 GiB RAM. See [Validation scope](docs/implementation.md) for the tested environment and remaining checks.

The installer has isolated tests. A fresh installation through the CLI and the release publishing workflow still need end-to-end validation; use `--source` until prebuilt releases are available.

## Collection scope

- Reads message bodies, types, times and conversation/sender IDs still present in the tablet database. [Message queries](docs/mcp-queries.md) add supported local display names, time filters and surrounding conversation context. Resumes from the last stored position after an interruption.
- Does not restore the phone's entire chat history, retrieve original attachments, or synchronize edits and deletions.
- Opening a conversation manually in the web admin console may change its KakaoTalk read status.

## Documentation

| Task | Documentation |
| --- | --- |
| Install and sign in | [Installer and setup guide](docs/onboarding.md), [Linux](docs/install.md), [Mac](docs/local-redroid.md), [Admin console](docs/web-ui.md) |
| Configure administrator access | [Passkey setup and recovery](docs/passkeys.md) |
| Connect an AI client or use the API | [OAuth MCP](docs/dot-plugin.md), [HTTP API and stdio MCP](docs/api.md), [Events](docs/events.md) |
| Check status, restart, and back up | [Operations](docs/operations.md), [Security](docs/security.md) |
| Understand, change, and verify the implementation | [Architecture](docs/design.md), [Iris](docs/iris.md), [Development](docs/development.md), [Validation scope](docs/implementation.md) |

## Contributing

Bug reports, documentation improvements, and compatibility results are welcome. See [Contributing](CONTRIBUTING.md) for reporting guidelines and [Development](docs/development.md) for local checks and previews.

## License and attribution

A project-wide license has not yet been specified. The modified Iris build has its own licensing and source-distribution requirements; see [NOTICE](iris/NOTICE.md). This project is not an official Kakao service.
