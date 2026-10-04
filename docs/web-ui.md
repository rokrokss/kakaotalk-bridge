# Admin console

[README](../README.md) · [Installation](install.md)

Use the admin console to control the tablet and check login and collection status. You do not need ADB or scrcpy on the operator's computer.

## Access

For a remote server, forward the HTTPS port over SSH and open `https://localhost:18443/admin/`. The Mac Lima setup uses the same address. See [Installation](install.md#4-open-the-admin-console) for certificate setup.

With the installer, run `./bridge admin` to pair a browser and choose your admin password. For the older manual Lima deployment, use the [pairing command in its guide](local-redroid.md#3-start-and-sign-in); the installer does not adopt that VM automatically. Sessions last 30 minutes, or seven days with **Keep me signed in**, and survive container restarts. Revoke them under **Admin browsers**. `secrets/admin_token` is a recovery option. **Lock** ends only the admin session. See the [setup guide](onboarding.md) for private Tailscale HTTPS and recovery.

## First login

1. Prepare a Korean tablet and Aurora from the setup guide. Install KakaoTalk in Aurora, then select **Set up collection components**. Alternatively import a complete official APK set.
2. Select **Open KakaoTalk**. To enter text, select **Connect keyboard**, focus an input field on the tablet, then send a value through **Text input**.
3. In KakaoTalk, select **“Use with other devices” (“다른 기기와 함께 사용” in the Korean UI)**. In the console, select **KakaoTalk login → Check login options**. The check currently recognizes the Korean KakaoTalk UI. Stop if the option is missing or KakaoTalk asks to transfer the primary device.
4. After the check passes, finish signing in on the tablet. Manually verify that KakaoTalk still opens with the existing session on your phone.
5. Select both checkboxes and **Start collecting messages**. The precheck is valid for 30 minutes and must match the current app version and device.

Starting collection records your manual confirmation. The program does not control KakaoTalk's login behavior or prevent your phone from being signed out.

Use **Check login options** only on the screen before signing in. Once collection is approved, the button is disabled; use **Check status** for the current state. Check progress and results appear below the button. A failed check preserves existing approval and precheck records.

## Installation

Use **Prepare tablet and Aurora** on a fresh tablet, install KakaoTalk through the screen, then choose **Set up collection components**. APK import is also available through `./bridge import-apks /path/to/folder`.

KakaoTalk signatures are checked before first enrollment. An already enrolled tablet is left unchanged. These setup actions do not reset an existing collection approval. The legacy CLI `bootstrap` remains a maintenance action that does reset approval; it is not used by the setup wizard.

## Everyday use

The tablet screen appears on the left, with status and settings on the right. On smaller screens, they stack vertically. Screenshots refresh roughly every 1.2 seconds. Use clicks, drags, and the Android buttons below the screen to control the tablet.

**Text input** inserts text into the focused field and clears the web input. Text is masked by default. It is not automatically submitted until you press Enter or a button on the device. Opening a conversation manually may change its KakaoTalk read status.

**Pause** stops screen refreshes and clicks on the screen. Message collection and the Android buttons remain available.

## Reading status

**Check status** retrieves the current screen and saved confirmation records. After a device action or 60 seconds, the console prompts you to check again.

| Field | Meaning |
| --- | --- |
| Tablet | Login screen, signed-in screen, or connection state observed on the current screen |
| Phone | Time of the operator's manual confirmation or sign-out report |
| Collection approval | Whether the secondary-login confirmation matches the current app and device |
| Collecting messages | Recent Iris database access and collection approval are valid; this does not mean the entire chat history has been restored |

The phone session is not monitored automatically. Use **Phone confirmation** to check it manually again and update the timestamp. Records older than 24 hours are marked for rechecking.

If your phone has been signed out, select **Signed out · Stop collection**. This revokes collection approval. Restarting requires the login-option check and confirmation of both sessions.

## Troubleshooting

| Screen or situation | Action |
| --- | --- |
| Waiting for connection | Check that redroid has booted on the server, then refresh |
| Text is not entered | Connect the keyboard, then focus the KakaoTalk input field again |
| Start collection button is disabled | Check for a valid precheck and both checkboxes; refresh status if stale |
| Registration app opens after installation | Select Open KakaoTalk; Iris mode does not need notification access |
| Collection is approved but no messages arrive | [Check Iris status and logs](operations.md#check-status) |

Canceling the installation dialog leaves the setup unchanged. Use **Connections** to approve matching OAuth requests and disconnect clients. **Collection test and maintenance** checks reception without displaying message content.
