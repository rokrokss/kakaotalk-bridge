<h1><img src="docs/assets/wordmark.svg?v=6b1a99c" width="450" height="96" alt="KakaoTalk Bridge"></h1>

Connect your KakaoTalk messages to AI agents.

KakaoTalk Bridge is a personal server that collects your KakaoTalk messages on your own infrastructure and makes them available for browsing and search in ChatGPT and other MCP-compatible AI agents.

It runs redroid as a secondary tablet and reads messages through Iris. No separate tablet is required: run the stack with Docker Compose, then install and sign in to KakaoTalk through the web admin console.

[Installation](docs/install.md) · [Admin console](docs/web-ui.md) · [Connect ChatGPT](docs/dot-plugin.md) · [Operations and backups](docs/operations.md) · [Development](docs/development.md)

## Getting started

1. **Prepare a server.** Run the containers on Linux or in a Linux VM on an Apple Silicon Mac.
2. **Sign in to KakaoTalk.** Check the secondary-device option in the admin console, then sign in. Confirm on your phone that its existing session remains active before starting collection.
3. **Connect ChatGPT.** Connect the MCP server using OAuth, then request recent messages, search results, or collection status.

Connecting the plugin does not create event subscriptions or automated tasks. MCP Events are an [optional feature that requires a separate subscription](docs/events.md).

## Where does it run?

![Iris reads messages on a secondary tablet on your server and stores them locally. ChatGPT retrieves them through OAuth and MCP.](docs/assets/message-flow.svg)

| Component | Purpose | Access |
| --- | --- | --- |
| redroid + Iris | Run the secondary tablet and read its local message database | Internal server network |
| Collection API | Store, browse, and search messages; retain them for 30 days by default | Authenticated private HTTPS |
| Admin console | Control the tablet and confirm login status | Admin key + private HTTPS |
| MCP plugin | Provide message retrieval tools to ChatGPT | Public HTTPS + OAuth |

Messages and the KakaoTalk login session are stored in server volumes. Content retrieved through ChatGPT tools is sent to ChatGPT. See [Security](docs/security.md) for storage locations, keys, and access controls.

## Supported environments

| Environment | Requirements |
| --- | --- |
| Linux amd64 / arm64 | Docker Engine, Compose v2, and a kernel with Android binder support. [Linux installation](docs/install.md) |
| Apple Silicon Mac | Run inside a Lima Ubuntu VM. [Mac installation](docs/local-redroid.md) |

You must supply the KakaoTalk APK. Secondary login and Iris collection have been verified in an Ubuntu VM on Apple Silicon, with the user manually confirming that the phone session stayed active. Validation on amd64 covers image builds and API startup. See [Validation scope](docs/implementation.md).

## Collection scope

- Reads message bodies, types, and conversation/sender IDs still present in the tablet database. Resumes from the last stored position after an interruption.
- Does not restore the phone's entire chat history, retrieve original attachments or display names, or synchronize edits and deletions.
- Does not automatically monitor the phone session. **Do not sign in if the “Use with other devices” option (“다른 기기와 함께 사용” in the Korean KakaoTalk UI) is missing.** The login check currently recognizes the Korean KakaoTalk UI.
- MCP exposes no message-sending or tablet-control tools. Opening a conversation manually in the web console may change its read status.

## Documentation

| Task | Documentation |
| --- | --- |
| Install and sign in | [Linux](docs/install.md), [Mac](docs/local-redroid.md), [Admin console](docs/web-ui.md) |
| Connect ChatGPT or another client | [OAuth MCP](docs/dot-plugin.md), [HTTP API and stdio MCP](docs/api.md), [Events](docs/events.md) |
| Check status, restart, and back up | [Operations](docs/operations.md), [Security](docs/security.md) |
| Understand, change, and verify the implementation | [Architecture](docs/design.md), [Iris](docs/iris.md), [Development](docs/development.md), [Validation scope](docs/implementation.md) |

See [NOTICE](iris/NOTICE.md) for the modified Iris build's license and corresponding source distribution. This project is not an official Kakao service.
