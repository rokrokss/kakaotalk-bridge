# Admin console

[README](../README.md) · [Installation](install.md)

Use the admin console to check collection, configure AI connections, choose event
conversations and control the tablet. You do not need ADB or scrcpy on the
operator's computer.

## Access

Fresh installations open the printed localhost address, normally
`http://localhost:18789/admin/`. For a remote server, keep the
[SSH forwarding session](quickstart.md#local-and-ssh-admin-access) open. Existing
installations retain their configured address, including private HTTPS. Register
a [passkey](passkeys.md) once, then select **Sign in with a passkey**. Keep the
configured origin stable; a passkey for a server hostname does not work at
localhost. `./bridge admin` opens the configured address.

Admin does not require Tailscale or an OpenAI tunnel. An optional shared HTTPS
deployment serves `/admin/` and `/mcp` on the same port; its login page is public
unless your proxy denies admin routes. A private admin origin can stay separate
from public MCP. Bookmark the admin address for everyday use.

Sessions last 30 minutes, or seven days with **Keep me signed in**, and survive container restarts. Under **Tablet & settings**, revoke them in **Admin browsers** or add a backup in **Passkeys and recovery**. **Lock** ends only the bridge's admin session; it does not sign out the tablet's KakaoTalk app. If every key is lost, run `./bridge passkey-login --enroll` on the server. Missing passkey configuration keeps controls locked.

After the security update, sign in once again with your existing passkey. It replaces older admin browser sessions; your passkeys and MCP connections remain registered. Tablet setup, login confirmation and collection controls follow the same steps below.

## First login

After admin sign-in, fresh-device preparation and collection-component installation
run automatically. The page detects KakaoTalk installation without requiring a
refresh and opens it when preparation finishes. Existing enrollment and collection
approval are left intact. A failed preparation stops automatic actions until you
retry; login and both-session confirmations always require your input.

The **KakaoTalk setup** guide has three steps: **Prepare → Sign in → Collect**.
AI connection is optional and is configured separately.

1. Let automatic preparation finish, then [install **KakaoTalk by Kakao Corp.** in Aurora](#install-kakaotalk-in-aurora). Bridge detects installation and configures collection components automatically. Alternatively import a complete official APK set.
2. Use the tablet under **Tablet & settings**; **Open KakaoTalk** is available if needed. To enter text, select **Connect keyboard**, focus an input field on the tablet, then send a value through **Text input**.
3. In KakaoTalk, select **“Use with other devices” (“다른 기기와 함께 사용” in the Korean UI)**. In the console, select **KakaoTalk login → Check login options**. The check currently recognizes the Korean KakaoTalk UI. Stop if the option is missing or KakaoTalk asks to transfer the primary device.
4. After the check passes, finish signing in on the tablet. Manually verify that KakaoTalk still opens with the existing session on your phone.
5. Select both checkboxes and **Start collecting messages**. The precheck is valid for 30 minutes and must match the current app version and device.

Starting collection records your manual confirmation. The program does not control KakaoTalk's login behavior or prevent your phone from being signed out.

Use **Check login options** only on the screen before signing in. Once collection is approved, the button is disabled; use **Check status** for the current state. Check progress and results appear below the button. A failed check preserves existing approval and precheck records.

### Install KakaoTalk in Aurora

Use the virtual tablet shown in **Tablet & settings**. The **KakaoTalk setup**
guide displays these instructions while it is waiting for installation.

1. Select **Open store**. Review Aurora's welcome screens and terms and continue.
   If it asks for an installation method, choose **Session Installer**.
2. When prompted to allow app installation, open the Android settings for Aurora,
   enable **Allow from this source** (**이 출처 허용**), and use the tablet's
   **Back** button to return. This setting belongs to the virtual tablet.
3. Choose **Anonymous** sign-in. This is the store session; KakaoTalk sign-in
   comes later.
4. Search for **KakaoTalk** or **카카오톡** and select the app by **Kakao Corp.**
   Click the tablet's search field and use its on-screen keyboard to type
   **KakaoTalk**. Bridge's **Text input** becomes available after collection
   components are prepared.
5. Select **Install** and confirm Android's installation prompt if shown. Keep
   the admin page open while downloading and installing.
6. Wait for Bridge to finish preparing collection components and open KakaoTalk.
   The store instructions disappear and the next action becomes signing in.
   Follow the login-option check above **before completing KakaoTalk sign-in**.

| Where you are stuck | Next action |
| --- | --- |
| Anonymous sign-in or download fails | Read the store error and retry there. See [Aurora's troubleshooting guide](https://auroraoss.gitbook.io/wiki/troubleshooting-and-faqs/faqs/aurora-store). |
| Android blocks installation | Allow Aurora to install apps, return with **Back**, and retry **Install**. |
| App installed, but Bridge still shows store instructions | Select **Check again** in **KakaoTalk setup**. If preparation reports an error, follow it and select **Retry preparation**. |

Already have the complete official APK set? Use the [APK import alternative](#installation).
Aurora wording can vary by version and language; installation permission applies
to Aurora, and the app being installed should be KakaoTalk by Kakao Corp.

## Installation

Automatic preparation is the normal path. Manual **Prepare tablet and Aurora**
and **Set up collection components** actions remain under
**Tablet & settings → Installation** for recovery. APK import is also available
through `./bridge import-apks /path/to/folder`.

KakaoTalk signatures are checked before first enrollment. An already enrolled tablet is left unchanged. These setup actions do not reset an existing collection approval. The legacy CLI `bootstrap` remains a maintenance action that does reset approval; it is not used by the setup wizard.

## Everyday use

The **Your bridge** overview shows three independent signals:

| Card | Meaning |
| --- | --- |
| Message collection | Collector state and last observed collection time; **Partial history** does not promise the phone's entire history |
| Remote AI activity | Last successful tool call from an approved OAuth or tunnel connection, or a prompt to make the first call |
| Your phone | Your last manual confirmation; **Recheck needed** after 24 hours is a reminder, not an observed sign-out |

For a running collector, **KakaoTalk setup** and **Tablet & settings** start
collapsed. The navigation buttons open **AI connections**, **Conversation events**
or **Tablet & settings** directly. During initial setup the guide and tablet open
so you can finish sign-in.

Inside **Tablet & settings**, the tablet screen and settings appear side by side,
stacking on smaller screens. Screenshots refresh roughly every 1.2 seconds while
this section is open and the page is visible. Closing it stops screen polling,
not message collection. Use clicks, drags, and the Android buttons to control the
tablet.

**Text input** inserts text into the focused field and clears the web input. Text is masked by default. It is not automatically submitted until you press Enter or a button on the device. Opening a conversation manually may change its KakaoTalk read status.

**Pause** stops screen refreshes and clicks on the screen. Message collection and the Android buttons remain available.

## Reading status

**Check status** retrieves the current screen and saved confirmation records.
After a device action or 60 seconds, the screen inspection becomes stale. The UI
shows **Inspection out of date** and labels saved approval **Approved · last
inspection**, rather than treating elapsed time as revoked approval. Actions that
depend on current tablet state still require a fresh inspection.

| Field | Meaning |
| --- | --- |
| Tablet | Login screen, signed-in screen, or connection state observed on the current screen |
| Phone | Time of the operator's manual confirmation or sign-out report |
| Collection approval | Whether the secondary-login confirmation matches the current app and device |
| Collecting messages | Recent Iris database access and collection approval are valid; this does not mean the entire chat history has been restored |

The phone session is not monitored automatically. Choose **Review phone
confirmation**, check KakaoTalk on your phone, select the confirmation checkbox,
then **Update confirmation time**. If disabled, read the explanation below the
button; **Refresh tablet inspection** is offered when needed. Records older than
24 hours are marked for rechecking.

If your phone has been signed out, select **Signed out · Stop collection**. This revokes collection approval. Restarting requires the login-option check and confirmation of both sessions.

## AI connections

1. Open **AI connections → Add or change a connection**.
2. In **Where will you use your messages?**, choose **ChatGPT**, **An AI app on
   my computer**, **Another remote AI client**, or **Decide later**. **All
   connection options** exposes every method. ChatGPT offers a personal tunnel
   and HTTPS choices; desktop clients offer stdio; remote clients offer HTTPS.
3. Enter **Connection settings** and start setup. Existing methods can coexist;
   **Decide later** keeps existing connections. An existing connection's settings
   start collapsed; expand them when you want to make a change.
4. [Finish in your AI client](#finish-in-your-ai-client) using the saved address,
   tunnel ID or stdio configuration. HTTPS uses OAuth; a personal tunnel uses
   its approved private connection.
5. Ask the AI to check collector status, then retrieve a message you sent from
   your phone to verify the content.

The HTTPS field accepts either an origin such as `https://bridge.example.com` or
the full `https://bridge.example.com/mcp` address. Other paths, query strings and
embedded credentials are rejected. Your reverse proxy must already be routed;
this form does not configure external DNS or proxy services.

Tunnel setup requires an ID, runtime key and explicit access approval. A saved
key may be reused for the same ID; the browser never receives it back. Tailscale
setup requires explicit installation/public-exposure consent. Follow the provider
link if shown, then select **Continue setup**. The CLI alternative and web setup
service requirements are in [onboarding](onboarding.md#connect-an-ai-client-optional).

### Finish in your AI client

Keep admin open beside your AI client. **Server setup complete** means you can
continue with the saved **Connection instructions**; the client still needs its
own connection setup.

For ChatGPT, open [Plugins](https://chatgpt.com/plugins) in a web browser, select
**+ → Create custom MCP server**, and name it **KakaoTalk Bridge**. Use the row
matching the connection method you configured:

| Method in Bridge | What to enter in the client | Complete access |
| --- | --- | --- |
| Personal tunnel | Choose **Tunnel**, use the saved tunnel ID, and choose **No authentication** for this approved personal connection. | Bridge must show tunnel access allowed. If the tunnel is missing, check its workspace association and your Tunnels Read + Use permission. [Tunnel preparation](openai-tunnel.md#before-setup) |
| Existing HTTPS or Tailscale | Paste the saved **MCP server URL**, including `/mcp`, and select **OAuth**. In ChatGPT, choose CIMD if asked for registration and leave optional static client credentials blank. | Follow passkey consent, or match the code in admin **AI connections → Approve connection**. Return to the AI client to finish. |
| Local or SSH app | Use **Copy client configuration** in Bridge. Add the `kakaotalk` entry to the app's `mcpServers` configuration, preserving other servers; for form-based clients, copy the command and arguments. | Save and reload MCP connections or restart the client, then enable KakaoTalk Bridge. For SSH, verify access without an interactive password prompt. [Client examples](api.md#stdio-mcp) |

In ChatGPT, review the notice, create the plugin and install it. Select
**@KakaoTalk Bridge** in a conversation. If creation is unavailable, check
workspace permissions. The [official ChatGPT instructions](https://developers.openai.com/api/docs/guides/custom-mcp-server)
describe the current menus.

**Tailscale asks for approval:** open the link displayed by Bridge, finish the
requested sign-in or approval, then return to admin and select **Continue
setup**. Repeat if another approval is requested. Once the MCP URL is saved,
follow the HTTPS row above.

**Verify with your own message:** ask the connected AI to check collector status.
After collection starts, send yourself a distinctive message from your phone,
such as “Bridge check 14:32”, and ask the AI to find that exact text. Check the
returned text and time. For remote connections, admin's **Remote AI activity**
should record the successful request; local stdio activity is not recorded there.
An expired OAuth request needs a new connection attempt and matching code.

### Progress and recovery

One connection setup runs at a time. Its current stage and elapsed time remain
visible when you reopen the page. Closing the browser does not stop the server
job. A setup-service restart can interrupt a job; the UI opens that job for review
instead of silently resubmitting it.

Use **Review and retry** after a setup failure, correct the displayed settings
and submit again. A runtime key cleared from the form may need re-entry if it
was not saved. **Check again** repeats a failed server check. Submitted choices
are saved after successful setup; checks and failures do not overwrite the last
saved method. Unsaved edits are not guaranteed to survive a reload.

Saved HTTPS/tunnel instructions come from configuration, so they stay available
after a check, failure or reload. **Connection instructions** on the tunnel card
opens them directly. A saved configuration can still need approval or repair.

### What each status proves

| Signal | What it proves |
| --- | --- |
| Server setup/check complete | Configuration finished or a server-side check completed; not a completed connection from your AI client |
| Access allowed | This OAuth client or personal tunnel has permission; not evidence of a tool call |
| Waiting for first AI request | An approval exists but no successful tool call has been recorded for it |
| Successful tool call recorded | A remote MCP tool completed at the displayed time; not proof that the connection is reachable now |

Tool discovery and failed calls do not update activity. Logging starts with this
version; earlier successful calls are not backfilled. Local stdio calls are not
included. **Check server connection** checks services separately. Use **Refresh
connections** to refresh approvals/activity; it does not call your AI client.

For OAuth, consent happens in the connecting browser when admin and public MCP
use the same HTTPS passkey hostname with registered origins. With a separate
localhost/private admin hostname, match the browser's code in
**AI connections** and approve it there. A personal tunnel configured by CLI can
be approved with **Allow personal tunnel**. Disconnect an OAuth client or tunnel
from its card at any time; this is separate from locking the admin browser.

## Conversation events

Open **Conversation events**, search for a room and switch it from **Off** to
**Allowed**. **Allowed · no AI subscription yet** means the room is permitted but
you must still ask your connected AI to subscribe. A registered subscription
does not prove that the AI ran or displayed a notification. Expand **Conversation
identifier** when you need the exact reference for rooms with matching names.

All rooms start off. Turning one off cancels queued deliveries and filters pending
reads, without stopping collection or normal message search. See [MCP Events](events.md)
for subscription renewal and delivery limits.

## Troubleshooting

| Screen or situation | Action |
| --- | --- |
| Waiting for connection | Check that redroid has booted on the server, then refresh |
| Text is not entered | Connect the keyboard, then focus the KakaoTalk input field again |
| Start collection button is disabled | Check for a valid precheck and both checkboxes; refresh status if stale |
| Registration app opens after installation | Select Open KakaoTalk; Iris mode does not need notification access |
| Collection is approved but no messages arrive | [Check Iris status and logs](operations.md#check-status) |
| Waiting for first AI request after approval | Finish adding the connection in the AI client and ask it to check collector status |
| Setup needs attention or Setup was interrupted | Review the stage-specific message, then select **Review and retry** |
| Web setup is unavailable | Follow the displayed recovery instruction and the [setup service guide](operations.md#web-connection-setup) |

Canceling the installation dialog leaves the setup unchanged. Under **Tablet &
settings → Collection test and maintenance**, a collection test reports a newly
received row without displaying its content. It does not match a unique test
message: another incoming message can satisfy it. Retrieve the message from your
AI client to verify the exact content.
