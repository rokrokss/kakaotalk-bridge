<div align="center">

<img src="assets/logo.svg" width="88" height="88" alt="KakaoTalk Bridge logo">

<h1>KakaoTalk Bridge</h1>

**Your conversations. Answers from your AI.**

Find a plan, catch up on a conversation, or ask what changed.<br>
Connect the KakaoTalk messages you collect to ChatGPT or another MCP-compatible AI.

Self-hosted · Browser setup · Read-only message access

[Get started](#getting-started) · [Try a question](#try-your-first-question) · [Choose your AI](#connect-your-ai) · [Guides](#documentation)

</div>

## Getting started

Run Bridge on an Apple Silicon Mac or a compatible Linux server. It uses a virtual
Android tablet while you keep using your phone—no physical tablet needed.
[Platform requirements](#requirements-and-validation)

Open Terminal on that machine and run:

```bash
curl -fsSL https://raw.githubusercontent.com/rokrokss/kakaotalk-bridge/main/install.sh | bash
```

The installer downloads and starts Bridge, then opens setup in your browser.
Run the same command again to resume or reopen it.

Already downloaded the project? Run `bash install.sh` from its folder.
[Full installation guide, including Windows and remote servers →](docs/quickstart.md)

<p align="center">
  <picture>
    <source media="(max-width: 600px)" srcset="docs/assets/readme-journey-mobile.svg">
    <img src="docs/assets/readme-journey.svg" width="1120" alt="Three steps: open Bridge in your browser, sign in to KakaoTalk and confirm both sessions, then connect an AI and try a message you sent.">
  </picture>
</p>

1. **Open your bridge.** Save a passkey. Bridge prepares the tablet automatically;
   install **KakaoTalk by Kakao Corp.** in its on-screen store.
2. **Sign in with your phone still connected.** In KakaoTalk, select **다른 기기와
   함께 사용** (“Use with other devices”), then run **Check login options** in
   admin. Finish signing in, check that your phone's existing session still works,
   and confirm both sessions to **Start collecting messages**.
3. **[Connect your AI](#connect-your-ai).** Follow the connection form, or choose
   **Decide later** and keep collecting.

The login check currently recognizes the Korean KakaoTalk UI. Stop if the
secondary-device option is missing or the app asks to transfer your primary
account. [Step-by-step sign-in help →](docs/web-ui.md#first-login)

## Try your first question

Send yourself these two messages from your phone after collection starts:

> Friday meetup is at 7 PM. Same café as last time.
>
> Friday meetup moved to 7:30 PM. Same place.

Ask your connected AI: **“Find my messages about Friday's meetup. What time is it,
and did the place change?”** Check that it found both messages.

<p align="center">
  <picture>
    <source media="(max-width: 600px)" srcset="docs/assets/readme-example-mobile.svg">
    <img src="docs/assets/readme-example.svg" width="1120" alt="Illustrative example with synthetic messages: a meetup moves from 7 PM to 7:30 PM at the same café. Your AI retrieves both messages and explains what changed.">
  </picture>
</p>

You can also ask for **conversation summaries**, **messages by keyword or date**,
or **collector status**.

## Connect your AI

Open **AI connections → Add or change a connection** and choose where you'll use
your messages. Multiple methods can stay enabled.

| Where you want to use it | Choose in admin | What you need |
| --- | --- | --- |
| ChatGPT, without a public server address | **Personal tunnel · no public address** | An OpenAI tunnel ID and runtime API key. [Tunnel guide](docs/openai-tunnel.md) |
| ChatGPT or another remote AI, through HTTPS | **Use my existing HTTPS address** or **Create an HTTPS address with Tailscale** | A configured HTTPS proxy, or Tailscale Funnel. [HTTPS guide](docs/dot-plugin.md) |
| An AI app on your computer | **Run Bridge from my AI app · local or SSH** | A client that can launch an MCP command; SSH access for a remote server. [Client configuration](docs/api.md#stdio-mcp) |

Follow the form, then finish adding the connection in your AI client.
[Step-by-step connection guide →](docs/web-ui.md#finish-in-your-ai-client)

**Verify:** ask your AI to check collector status and find a message you sent.
A server check alone does not verify AI access.

## How the connection methods work

### Personal OpenAI tunnel

Your server connects outbound to OpenAI; no public MCP address is needed.
Admin access stays separate.

<img src="docs/assets/connection-tunnel.svg" width="960" alt="An outbound OpenAI connection carries MCP requests to your server. Admin access and personal tunnel approval are separate.">

### HTTPS with OAuth

Your AI connects to a public MCP address. Approve with your passkey or a matching
code in private admin.

<img src="docs/assets/connection-https.svg" width="960" alt="Shared-HTTPS example: a client reaches MCP through Funnel or a reverse proxy. The owner approves with a passkey, then the client uses OAuth.">

### stdio, locally or over SSH

Your AI app starts Bridge's adapter on your computer or over SSH.

<img src="docs/assets/connection-stdio.svg" width="960" alt="Your AI app starts a local or SSH stdio adapter, which reads collected messages from the server.">

[Architecture](docs/design.md) · [Editable diagrams](docs/assets/connection-methods.drawio)

## Your everyday view

Use admin to check collection, AI activity and your phone confirmation.

<p align="center">
  <img src="docs/assets/admin-overview.png" width="1120" alt="KakaoTalk Bridge admin overview showing message collection, recorded remote AI activity and manual phone confirmation, with links to AI connections, conversation events and tablet settings. Synthetic demo data.">
</p>

*Actual admin UI with synthetic data.* Phone status is manually confirmed.
AI activity records past remote calls, not live availability; local stdio is excluded.

For optional new-message events, set a room to **Allowed** in **Conversation
events**, then ask your AI to subscribe. [Event setup and limits →](docs/events.md)

[Admin guide](docs/web-ui.md) · [Restart, update or recover](docs/operations.md) ·
[Passkeys and recovery](docs/passkeys.md)

## Requirements and validation

| Where Bridge runs | What to expect |
| --- | --- |
| Apple Silicon Mac | Best-tested: dedicated Lima Linux VM, no Docker Desktop required. Secondary login, collection and AI access verified. |
| Linux amd64 / arm64 | Requires Docker Engine, Compose v2 and Android Binder on a dedicated host or VM. KakaoTalk/redroid compatibility outside the tested Mac/Lima setup remains unverified. |
| Windows | Requires an existing Linux server or Binder-enabled WSL2. Windows execution remains unverified. |

The Mac VM is configured with 6 CPUs and 8 GiB RAM; these are not measured minimums.
[Prerequisites](docs/quickstart.md#platforms)

HTTPS/OAuth and tunnel message access have been tested; stdio has protocol tests.
Full fresh installs across all hosts and end-to-end AI events remain unverified.
[Validation details →](docs/implementation.md)

## Your data and collection scope

- **Your infrastructure.** Messages are kept for 30 days by default; requested
  results are shared with your connected AI.
- **Read-only MCP.** Search and retrieve messages; no sending or tablet control.
- **Partial history.** Only messages available on the secondary tablet. No full
  phone history, original attachments, or edit/deletion synchronization.
- **Manual checks.** Opening chats on the tablet can change read status. Check
  your phone session yourself.

Use a dedicated host or VM: available official redroid images have old Android
security patches. [Security and remaining risk](docs/security.md) ·
[How collection works](docs/iris.md)

## Documentation

| I want to… | Start here |
| --- | --- |
| Install and sign in | [Quick start](docs/quickstart.md) · [Admin guide](docs/web-ui.md) |
| Connect my AI | [OpenAI tunnel](docs/openai-tunnel.md) · [HTTPS/OAuth](docs/dot-plugin.md) · [Local/SSH client](docs/api.md#stdio-mcp) |
| Choose conversations for events | [MCP Events](docs/events.md) |
| Manage access, update or recover | [Passkeys](docs/passkeys.md) · [Operations](docs/operations.md) |
| Deploy or develop the internals | [Advanced setup](docs/onboarding.md) · [Architecture](docs/design.md) · [Development](docs/development.md) |

Existing deployments: read the [security upgrade notes](docs/operations.md#upgrading-to-the-security-update).
[Contributing](CONTRIBUTING.md)

## License and attribution

A project-wide license has not yet been specified. The modified Iris build has
its own [license and source-distribution requirements](iris/NOTICE.md).
KakaoTalk Bridge is not an official Kakao service.
