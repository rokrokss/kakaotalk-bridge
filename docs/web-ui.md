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

1. Let automatic preparation finish, then install **KakaoTalk by Kakao Corp.** in the on-screen Aurora store. Bridge detects installation and configures collection components automatically. Alternatively import a complete official APK set.
2. Use the tablet under **Tablet & settings**; **Open KakaoTalk** is available if needed. To enter text, select **Connect keyboard**, focus an input field on the tablet, then send a value through **Text input**.
3. In KakaoTalk, select **“Use with other devices” (“다른 기기와 함께 사용” in the Korean UI)**. In the console, select **KakaoTalk login → Check login options**. The check currently recognizes the Korean KakaoTalk UI. Stop if the option is missing or KakaoTalk asks to transfer the primary device.
4. After the check passes, finish signing in on the tablet. Manually verify that KakaoTalk still opens with the existing session on your phone.
5. Select both checkboxes and **Start collecting messages**. The precheck is valid for 30 minutes and must match the current app version and device.

Starting collection records your manual confirmation. The program does not control KakaoTalk's login behavior or prevent your phone from being signed out.

Use **Check login options** only on the screen before signing in. Once collection is approved, the button is disabled; use **Check status** for the current state. Check progress and results appear below the button. A failed check preserves existing approval and precheck records.

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
4. Finish in your AI client using the saved address, tunnel ID or stdio
   configuration. HTTPS uses OAuth; a personal tunnel uses its approved private
   connection. See [HTTPS/OAuth](dot-plugin.md), [OpenAI tunnel](openai-tunnel.md)
   and [stdio](api.md#stdio-mcp).
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
