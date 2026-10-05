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

Run Bridge on your Apple Silicon Mac or a compatible Linux server. A virtual
Android tablet runs on that machine; you keep using KakaoTalk on your phone.
No physical tablet is needed. [Platform requirements](#requirements-and-validation)

From the downloaded project folder:

```bash
bash install.sh
```

The installer prepares the environment, starts Bridge and opens the setup page.
Run the same command again to resume or reopen it.
[Full installation guide, including Windows and remote servers →](docs/quickstart.md)

<p align="center">
  <picture>
    <source media="(max-width: 600px)" srcset="docs/assets/readme-journey-mobile.svg">
    <img src="docs/assets/readme-journey.svg" width="1120" alt="Three steps: open Bridge in your browser, sign in to KakaoTalk and confirm both sessions, then connect an AI and try a message you sent.">
  </picture>
</p>

1. **Open your bridge.** Save a passkey when prompted. Bridge prepares the virtual
   tablet automatically. Install **KakaoTalk by Kakao Corp.** in the on-screen
   store; Bridge finishes preparing collection for you.
2. **Sign in with your phone still connected.** In KakaoTalk, select **다른 기기와
   함께 사용** (“Use with other devices”), then run **Check login options** in
   admin. Finish signing in, check that your phone's existing session still works,
   and confirm both sessions to **Start collecting messages**.
3. **Connect the AI you use.** Open **AI connections → Add or change a connection**,
   choose where you will use your messages and follow the instructions. You can
   also choose **Decide later** and keep collecting.

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

Bridge supplies the collected messages; your AI writes the answer. You can also
ask it to **summarize recent messages in a conversation**, **find a message by
keyword or date**, or **check whether collection is running**.

## Connect your AI

Start with **Where will you use your messages?** in the admin connection form.
You can keep multiple methods enabled. **Tailscale and OpenAI tunnels are both
optional.**

| Where you want to use it | Choose in admin | What you need |
| --- | --- | --- |
| ChatGPT, without a public server address | **Personal tunnel · no public address** | An OpenAI tunnel ID and runtime API key. [Tunnel guide](docs/openai-tunnel.md) |
| ChatGPT or another remote AI, through HTTPS | **Use my existing HTTPS address** or **Create an HTTPS address with Tailscale** | A configured HTTPS proxy, or Tailscale Funnel. [HTTPS guide](docs/dot-plugin.md) |
| An AI app on your computer | **Run Bridge from my AI app · local or SSH** | A client that can launch an MCP command; SSH access for a remote server. [Client configuration](docs/api.md#stdio-mcp) |

Enter the requested details, follow setup progress, then finish adding the
connection in your AI client. Creating an OpenAI tunnel and selecting it in
ChatGPT are still provider-side steps. Tunnel access approval is included in the
web form and has no automatic expiration; disconnect it whenever you want.

**Verify the connection:** ask your AI to check collector status. Admin shows
access approval separately from the last successful remote tool call. A server
check alone does not confirm that your AI can use the connection.

Saved connection instructions survive checks and reloads. Use **Connection
settings** to edit them or **Review and retry** after a setup failure.
[Detailed connection workflow →](docs/web-ui.md#ai-connections)

<details>
<summary><strong>How the connection methods work</strong></summary>

### Personal OpenAI tunnel

Your server opens an outbound connection to OpenAI. MCP requests return through
it, so you need no inbound MCP port or public HTTPS address. Admin uses its own
localhost, SSH or HTTPS address.

<img src="docs/assets/connection-tunnel.svg" width="960" alt="An outbound OpenAI connection carries MCP requests to your server. Admin access and personal tunnel approval are separate.">

### HTTPS with OAuth

Your client connects to a public MCP address. Approve with your passkey for a
shared HTTPS hostname, or match its code in your private admin console.

<img src="docs/assets/connection-https.svg" width="960" alt="Shared-HTTPS example: a client reaches MCP through Funnel or a reverse proxy. The owner approves with a passkey, then the client uses OAuth.">

### stdio, locally or over SSH

Your AI app starts the Bridge adapter and reads messages through it. The adapter
can run on your computer or on a server reached through SSH.

<img src="docs/assets/connection-stdio.svg" width="960" alt="Your AI app starts a local or SSH stdio adapter, which reads collected messages from the server.">

[Editable connection diagrams](docs/assets/connection-methods.drawio) ·
[Architecture](docs/design.md) · [Terminal setup](docs/onboarding.md#connect-an-ai-client-optional)

</details>

## Your everyday view

Open your bookmarked admin page to see collection status, the last successful
remote AI call and your last manual phone confirmation. Installation and tablet
controls stay out of the way until you need them.

<p align="center">
  <img src="docs/assets/admin-overview.png" width="1120" alt="KakaoTalk Bridge admin overview showing message collection, recorded remote AI activity and manual phone confirmation, with links to AI connections, conversation events and tablet settings. Synthetic demo data.">
</p>

*Actual admin UI with synthetic demo data.* The phone status is your manual
confirmation, not automatic monitoring. AI activity is a past success, not a
live availability check; local stdio calls are not included.

Want new-message events for certain conversations? In **Conversation events**,
change a room from **Off** to **Allowed**, then ask your AI to subscribe. A room's
permission and the AI's subscription are separate. Events are optional; normal
collection and search work without them. [Event setup and limits →](docs/events.md)

[Admin guide](docs/web-ui.md) · [Restart, update or recover](docs/operations.md) ·
[Passkeys and recovery](docs/passkeys.md)

## Requirements and validation

| Where Bridge runs | What to expect |
| --- | --- |
| Apple Silicon Mac | Best-tested path. The installer manages a dedicated Lima Linux VM; Docker Desktop is not required. Real secondary login, collection and AI access have been verified. |
| Linux amd64 / arm64 | Docker Engine, Compose v2 and Android Binder support required. Use a dedicated host or VM. KakaoTalk/redroid compatibility outside the tested Apple Silicon Lima environment remains unverified. |
| Windows | Use an existing Linux server or a Binder-enabled WSL2 distribution. The entry point is provided; Windows execution remains unverified. |

The supplied Mac VM uses 6 CPUs and 8 GiB RAM. These are configured resources,
not measured minimums. [Installation scope and prerequisites](docs/quickstart.md#platforms)

Real HTTPS/OAuth and OpenAI tunnel message access have been tested. stdio has
protocol tests; verify your chosen client. End-to-end AI event execution and a
complete fresh install across every host remain unverified.
[Detailed validation scope →](docs/implementation.md)

## Your data and collection scope

- **Stored on your infrastructure.** Collected messages are kept for 30 days by
  default. Requested results are shared with the AI client you connect.
- **Read-only access to KakaoTalk.** MCP can search and retrieve collected
  messages; it cannot send KakaoTalk messages or control the tablet.
- **A partial history.** Bridge reads what is available on its secondary tablet.
  It does not restore your phone's entire history, retrieve original attachments,
  or synchronize edits and deletions.
- **Manual controls have effects.** Opening a conversation on the admin tablet
  can change its KakaoTalk read status. Your phone session needs manual checks.

Redroid requires a dedicated host or VM and its available official images have
old Android security patches. See the [security boundaries and remaining risk](docs/security.md)
before deployment. [How messages are collected →](docs/iris.md)

## Documentation

| I want to… | Start here |
| --- | --- |
| Install and sign in | [Quick start](docs/quickstart.md) · [Admin guide](docs/web-ui.md) |
| Connect my AI | [OpenAI tunnel](docs/openai-tunnel.md) · [HTTPS/OAuth](docs/dot-plugin.md) · [Local/SSH client](docs/api.md#stdio-mcp) |
| Choose conversations for events | [MCP Events](docs/events.md) |
| Manage access, update or recover | [Passkeys](docs/passkeys.md) · [Operations](docs/operations.md) |
| Deploy or develop the internals | [Advanced setup](docs/onboarding.md) · [Architecture](docs/design.md) · [Development](docs/development.md) |

For an existing deployment crossing the security migration, read the
[upgrade notes](docs/operations.md#upgrading-to-the-security-update) before updating.
Bug reports and contributions are welcome: [Contributing](CONTRIBUTING.md).

## License and attribution

A project-wide license has not yet been specified. The modified Iris build has
its own [license and source-distribution requirements](iris/NOTICE.md).
KakaoTalk Bridge is not an official Kakao service.
