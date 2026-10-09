<div align="center">

<img src="assets/logo.svg" width="88" height="88" alt="KakaoTalk Bridge logo">

<h1>KakaoTalk Bridge</h1>

An MCP server that lets your AI search, analyze, and send KakaoTalk messages.

Self-hosted · Set up in your browser · Read and send messages

[Why a virtual tablet](#why-a-virtual-tablet) · [Getting started](#getting-started) · [Try your first question](#try-your-first-question) · [Connect your AI](#connect-your-ai) · [Documentation](#documentation)

[한국어](README.md) · English

</div>

> The admin console, terminal prompts, and linked documentation are in Korean. Screen labels below are quoted in Korean, followed by an English gloss.

<a id="why-a-virtual-tablet"></a>
## Why a virtual tablet?

**KakaoTalk offers no public API for reading or receiving messages from personal chats.** The official message API is for sending, not for retrieving existing conversations. [Kakao's API notice (Korean)](https://devtalk.kakao.com/t/api/139501)

KakaoTalk limits how many devices can be signed in to the same account at once. If the collecting Android signs in as your primary device, your existing phone may be signed out. To keep using your phone, sign in on the tablet with **다른 기기와 함께 사용** (use together with another device).

Bridge runs a virtual Android tablet with redroid, along with KakaoTalk and Iris. Iris reads the tablet's message database, stores the messages on your server, and serves them over MCP. No physical tablet is needed. [Collection design and sign-in conditions](docs/iris.md#components-and-assumptions)

<a id="getting-started"></a>
## Getting started

Run this in a terminal on an Apple Silicon Mac or a Linux server. [Requirements](#requirements-and-validation)

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

When it finishes, the admin console opens in your browser. From then on, run commands such as `kakaotalk-bridge doctor` from any folder. If Bridge is already installed, the same command updates it to the latest version for your install type. For a server without a display, see [installing over SSH](docs/quickstart.md#local-and-ssh-admin-access).

<p align="center">
  <picture>
    <source media="(max-width: 600px)" srcset="docs/assets/readme-journey-mobile.svg">
    <img src="docs/assets/readme-journey.svg" width="1120" alt="Three steps: open Bridge in the browser, sign in to KakaoTalk and confirm both devices stay signed in, then connect an AI and find a message you sent">
  </picture>
</p>

1. **Install KakaoTalk:** Create a passkey, sign in anonymously to the tablet's store (Aurora), and install **KakaoTalk by Kakao Corp.**
2. **Sign in and collect:** Sign in with **다른 기기와 함께 사용** (use together with another device), confirm your phone stays signed in, then press **메시지 수집 시작** (start collecting messages).
3. **[Connect your AI](#connect-your-ai) (optional):** Choose where to use your messages under **AI 연결 → AI 연결 설정** (AI connection → connection setup).

> Stop if the **다른 기기와 함께 사용** option is missing or KakaoTalk asks you to migrate your device. KakaoTalk on your phone may be signed out.

[Install and run guide →](docs/quickstart.md) · [Screen-by-screen details →](docs/web-ui.md#first-login)

<a id="try-your-first-question"></a>
## Try your first question

Once collection is running and [your AI is connected](#connect-your-ai), send yourself messages like the example below from your phone. Ask your AI when and where the meetup is, and check that it finds both messages.

<p align="center">
  <picture>
    <source media="(max-width: 600px)" srcset="docs/assets/readme-example-mobile.svg">
    <img src="docs/assets/readme-example.svg" width="1120" alt="Synthetic message example: a meetup at the same café moves from 7:00 to 7:30 PM. The AI finds both messages and explains the change.">
  </picture>
</p>

You can also ask for **conversation summaries**, **message search by keyword or date**, and **collection status**. With send permission set up, you can send text to an existing chat, such as "Tell this chat I'll arrive at 7." [Sending messages](docs/sending.md)

<a id="connect-your-ai"></a>
## Connect your AI

Choose where to use your messages under **AI 연결 → AI 연결 설정** (AI connection → connection setup). You can use several connection methods together.

| Where you want to use it | Choose in the admin console | What you need |
| --- | --- | --- |
| ChatGPT without a public server address | **ChatGPT → 개인 터널** (personal tunnel) | An OpenAI tunnel ID and a runtime API key. [Tunnel guide](docs/openai-tunnel.md) |
| ChatGPT or another remote AI over HTTPS | **기존 HTTPS 주소** (existing HTTPS address) or **Tailscale로 주소 만들기** (create an address with Tailscale) | A configured HTTPS proxy or Tailscale Funnel. [HTTPS guide](docs/dot-plugin.md) |
| An AI app on your computer | **내 컴퓨터의 AI 앱** (AI app on my computer) | A client that can run an MCP command, plus SSH access if the server is remote. [Client setup](docs/api.md#stdio-mcp) |

After saving the settings, [add the connection in your AI app as well](docs/web-ui.md#finish-in-your-ai-client).

<a id="how-the-connection-methods-work"></a>
## How the connection methods work

### Personal OpenAI tunnel

Your server connects out to OpenAI, so no public MCP address is needed.

<img src="docs/assets/connection-tunnel.svg" width="960" alt="The server connects to OpenAI and relays MCP requests. Access to the admin console and approval of the personal tunnel are separate.">

### HTTPS and OAuth

The AI connects to a public MCP address and reaches your messages after OAuth approval.

<img src="docs/assets/connection-https.svg" width="960" alt="Public HTTPS example: the client reaches MCP through Funnel or a reverse proxy. Once the owner approves with a passkey, the client uses OAuth.">

### stdio, locally or over SSH

Your AI app runs the Bridge adapter on your computer or over SSH.

<img src="docs/assets/connection-stdio.svg" width="960" alt="The AI app runs a local or SSH stdio adapter that reads the messages collected on the server.">

[Architecture](docs/design.md) · [Editable connection diagram](docs/assets/connection-methods.drawio)

<a id="your-everyday-view"></a>
## Admin console

See collection status, remote AI activity, and when your phone was last checked.

<p align="center">
  <img src="docs/assets/admin-overview.png" width="1120" alt="KakaoTalk Bridge admin console with synthetic data: message collection, remote AI activity, the phone status you confirmed, and menus for AI connection, conversation events, and tablet settings">
</p>

*The admin console, shown with synthetic data.*

To use new-message events, **허용** (allow) the conversation under **대화 이벤트** (conversation events), and ask your AI to subscribe as well. [Event setup and limits →](docs/events.md)

<a id="requirements-and-validation"></a>
## Requirements

| Environment | Support and validation status |
| --- | --- |
| Apple Silicon Mac | Uses a dedicated Lima Linux VM. Docker Desktop is not required. |
| Linux amd64 / arm64 | Needs Docker Engine, Compose v2, and Android Binder on a dedicated host or VM. KakaoTalk and redroid compatibility outside the validated Mac/Lima setup has not been confirmed yet. |
| Windows | Needs an existing Linux server or WSL2 with Binder support. Running on Windows has not been validated yet. |

The Mac VM is configured with 6 CPUs and 8 GiB of memory. This is not a measured minimum.
[Platform install guide](docs/quickstart.md#platforms) · [Validation record](docs/implementation.md)

<a id="your-data-and-collection-scope"></a>
## Your data and collection scope

- **Retention:** Collected messages are kept on the server you installed for 30 days by default. Results you request are sent to the AI you connected.
- **Permissions:** MCP supports search and lookup, plus text sending under a separate permission. It provides no tools for controlling the tablet.
- **Collection scope:** Only messages shown on the secondary tablet are collected. Your phone's full history, original attachments, and edit or delete sync are not supported.
- **Read status:** Opening a conversation on the tablet may change its read status.

The official redroid image ships an outdated Android security patch, so use a dedicated host or VM.
[Security and remaining risks](docs/security.md) · [How collection works](docs/iris.md)

<a id="documentation"></a>
## Documentation

The documents below are in Korean.

| What you want to do | Read |
| --- | --- |
| Install and sign in | [Quick start](docs/quickstart.md) · [Admin console](docs/web-ui.md) |
| Connect your AI | [OpenAI tunnel](docs/openai-tunnel.md) · [HTTPS/OAuth](docs/dot-plugin.md) · [Local/SSH clients](docs/api.md#stdio-mcp) |
| Send messages | [Send permission, status, and limits](docs/sending.md) |
| Choose which conversations send events | [MCP Events](docs/events.md) |
| Manage access, update, and recover | [Passkeys](docs/passkeys.md) · [Operations](docs/operations.md) |
| Deploy or develop internals | [Advanced install](docs/onboarding.md) · [Architecture](docs/design.md) · [Development](docs/development.md) |

To update an existing install, run the install command again. [Updating an existing install](docs/operations.md#update)
[Contributing](CONTRIBUTING.md)

<a id="license-and-attribution"></a>
## License and attribution

This repository is available under the [MIT License](LICENSE). However, an Iris APK built from the `iris/` code together with the original Iris includes the original's GPL-3.0 files, so GPL-3.0 terms apply to the APK as a whole. [License and source distribution terms](iris/NOTICE.md)
KakaoTalk Bridge is not an official Kakao service.
