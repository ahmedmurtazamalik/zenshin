# Zenshin

**Keep moving forward.** A local companion for Codex that answers authorized desktop requests and performs individual Chrome password and terms actions.

Zenshin runs on your computer with a browser-based control page. You choose what it may do. For Chrome actions, Zenshin itself focuses the password field, opens and selects Chrome's generated-password suggestion, or checks the named terms box through Windows accessibility. Codex requests the action and receives a result; ChatGPT Computer Use is not needed for those interactions.

## Standalone Windows app

The standalone build runs without installing Python or pip packages. Codex desktop, the signed-in Codex CLI, and Chrome (for Chrome actions) are still prerequisites.

1. Download `zenshin-windows-x64.zip` from the build's artifacts or a release where it has been attached, then **Extract All** into a writable folder.
2. Double-click `Zenshin.exe`. It opens the browser control page. Keep its console window running; close it or press Ctrl+C there to stop Zenshin.
3. Choose **Connect Zenshin tools**. The standalone app registers its own executable as the MCP bridge; Python is not used.

Settings and the attempt journal remain in `.local/state.json` beside `Zenshin.exe`. For an update, stop the old app and replace the executable in the same folder, preserving `.local`. When moving from a source installation, copy its `.local` folder and remove the old MCP registration with `codex mcp remove zenshin` before connecting the standalone app. Do not run both installations together.

The executable bundles Python bytecode instead of distributing loose `.py` files. It can still be extracted or reverse engineered; packaging does not provide source-code secrecy. This is an unsigned portable application, so Windows may display a publisher warning. Linux currently uses the source setup below.

### Build in this repository

Run the **Standalone Windows app** workflow from GitHub Actions (or push a version tag). It builds on Windows x64, runs the existing tests and a bundled-executable smoke check, and uploads the ZIP plus `SHA256SUMS.txt` as workflow artifacts. It does not publish a release or change repository visibility. Attach these two files to a release when ready. Artifacts and releases in this private repository require repository access; packaging does not make their links public.

To build locally on Windows with Python 3.11:

```powershell
python -m pip install -r requirements-windows.txt -r requirements-build.txt
.\build-windows.ps1
```

The output is `dist/zenshin-windows-x64.zip`. The smoke check runs the executable without Python on PATH, checks bundled assets, saves and reloads settings, and exercises MCP discovery and transport. Native Codex/Chrome interactions still require a live Windows check. `Zenshin.exe --no-browser` suppresses opening the control page, and `--port` / `--state` work as in source mode.

## Source downloads v0.2.0

| Platform | Download | Included features |
| --- | --- | --- |
| Windows | [Download Windows source ZIP](https://github.com/ahmedmurtazamalik/zenshin/releases/download/v0.2.0/zenshin-v0.2.0-windows-source.zip) | Codex chat monitoring and native Chrome actions |
| Linux | [Download Linux source tar.gz](https://github.com/ahmedmurtazamalik/zenshin/releases/download/v0.2.0/zenshin-v0.2.0-linux-source.tar.gz) | Codex chat monitoring; Chrome actions are Windows-only |

[Release page](https://github.com/ahmedmurtazamalik/zenshin/releases/tag/v0.2.0) · [Checksums](https://github.com/ahmedmurtazamalik/zenshin/releases/download/v0.2.0/SHA256SUMS.txt) · [Release notes](RELEASE_NOTES.md)

**These are source downloads, not standalone executables or installers.** Install Python and the Codex CLI first. Python 3.11 is the verified runtime. macOS is not supported.

## What it does

- Answers offered choices, custom text, multi-question forms, ordinary continuation requests, and recognized one-time approval cards in selected Codex desktop chats.
- Uses exact question/reply rules or AI standing instructions through your signed-in Codex CLI.
- Offers Preview mode, Start/Pause, saved settings, progress, activity, and a durable attempt journal that prevents duplicate delivery.
- Provides one-time Codex tool registration, connection checks, and a first-visit tutorial that can be replayed from **Take the tour**.
- On Windows, exposes `select_chrome_password` and `check_chrome_terms` so Codex can delegate individual Chrome actions and continue in the same turn.

## Before you start (source installation)

1. Install Python. On Windows, use [Python's official download](https://www.python.org/downloads/windows/) and check that `py -3 --version` works. Python 3.11 was used for verification.
2. Install and sign into the Codex desktop app for chat monitoring. Install the [Codex CLI](https://learn.chatgpt.com/docs/codex/cli) on the same computer. If you already use npm, you can install it with `npm install -g @openai/codex`.
3. In a terminal, run:

   ```text
   codex --version
   codex login
   codex login status
   ```

   Follow the sign-in instructions. See [Codex authentication](https://learn.chatgpt.com/docs/auth) for account setup.
4. For Chrome actions, use Windows and Google Chrome with its password-generation feature available. The intended page must already be open. Zenshin does not change Chrome settings or sign you into Chrome.

Run Zenshin in your normal signed-in desktop session with the computer unlocked. Native Windows features require native Windows Python and Codex, rather than WSL. AI decisions consume your Codex account's model usage.

## Windows setup

1. Download the Windows ZIP above and choose **Extract All**. Work in the extracted `zenshin-0.2.0` folder, not inside the ZIP.
2. Open PowerShell in that folder and run:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements-windows.txt
   .\.venv\Scripts\python.exe app.py
   ```

3. Open [http://127.0.0.1:8765](http://127.0.0.1:8765) in your browser. Keep the terminal running. No virtual-environment activation or PowerShell execution-policy change is needed.

For later launches, run only:

```powershell
.\.venv\Scripts\python.exe app.py
```

The Windows dependency is `uiautomation`, which installs `comtypes`. There is no frontend build. [Windows implementation and verification details](WINDOWS.md).

## Linux setup

Download the Linux archive, then extract and launch it:

```sh
tar -xzf zenshin-v0.2.0-linux-source.tar.gz
cd zenshin-0.2.0
python3 app.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Linux has no pip dependencies or frontend build. Desktop control requires the system Python `gi` package and AT-SPI; on Ubuntu/Debian these are normally provided by `python3-gi` and `gir1.2-atspi-2.0`. Use your desktop's system Python so it can load them. GNOME Wayland custom-text input also requires Mutter RemoteDesktop support. Enable desktop accessibility and run within an unlocked graphical session.

Linux chat navigation still needs a fresh live check with a readable accessibility tree. Chrome password and terms tools are not supported on Linux.

## Set up and use the app

The numbered sidebar takes you through the workflow. The welcome tutorial highlights the controls without changing settings or sending actions. Replay it anytime with **Take the tour**.

### 1. Connect to Codex

Choose **Connect Zenshin tools** to register this installation's MCP bridge with your Codex CLI. Zenshin generates the correct executable, folder, and port arguments. It reuses a matching registration and leaves a different or disabled registration unchanged, with recovery instructions. Other MCP entries and approval settings are preserved.

Reload Codex's MCP connections or restart Codex. In the working chat, ask:

> Confirm that Zenshin's select_chrome_password and check_chrome_terms tools are available. Do not call them yet.

Use **Copy Codex instructions** and put that guidance in your working chat or its project's `AGENTS.md`, alongside your task authorization. Registration alone does not authorize an action.

**Check connection** reports two separate things: whether the tools are registered, and whether Zenshin's chat-history connection responds. Registration does not prove that an existing Codex chat has loaded its tools. A disconnected chat-history connection does not prevent registered Chrome tools from working.

If registration fails, expand **Manual setup or troubleshooting** and use the command generated for your installation. Reconnect after moving Zenshin or changing its port.

### 2. Chrome actions — Windows

Enable the password action, terms action, or both. In **Monitor**, choose **Send authorized replies**, then **Save changes**.

- **Password:** Codex supplies the current page URL. Zenshin locates one visible new-password field, focuses it, invokes Chrome's native Suggest password command if needed, and selects the suggestion once. Chrome generates and fills the password. Confirmation/current/old-password fields are excluded from target selection. No password values are returned or logged.
- **Terms:** Codex supplies the current page URL and the exact checkbox label. Zenshin checks one matching, unchecked agreement box. Marketing opt-ins are excluded.

Zenshin performs these interactions using Windows UI Automation, without ChatGPT screenshots, coordinate clicks, or keyboard injection. The page must already be open and loaded. The individual actions do not open new Chrome windows, navigate, submit an account, solve CAPTCHA, or bypass a safety refusal or URL-policy stop.

Keep Zenshin running. These tools do not need selected chats or a running chat monitor. **Pause stops chat monitoring only.** To revoke Chrome actions, disable their toggles and save, or save **Preview only** mode.

The Chrome section also has manual **Open and verify in Chrome** and **Fill Chrome's suggested password** controls. The first explicitly opens the requested URL; the second performs the native password action on that page.

### 3. Chats

Choose **Load Codex chats**, then select the conversations to monitor. Give each selected chat a unique title and keep only one visible copy. If a new chat is missing from the list, use **Add a chat by ID**.

**Check connection** here sends one read-only request through the existing Codex connection. If disconnected, choose **Load Codex chats** to reconnect. This connection reads identity/history; it does not control another client's approvals through internal IPC.

### 4. Authorization

Choose either:

- **AI · follow my instructions:** write narrow standing instructions, such as “Continue formatting this report. Ask me for missing facts or decisions outside that task.” AI examines recent context and the current request; missing facts and uncovered decisions stay for you.
- **Match exact questions:** save the complete expected question and its reply. Matching normalizes whitespace and otherwise requires the full question.

AI analysis uses your signed-in Codex CLI, times out after 60 seconds, and is canceled by Pause or changed settings. Invalid decisions and CLI failures stop monitoring without sending.

### 5. Monitor

Start in **Preview only** to inspect suggested chat replies. Choose **Send authorized replies** when your rules or instructions cover the work, then **Start monitoring**.

Keep the control page open for five-second polling. Desktop mode visits selected chats one at a time. An ordinary reply requires a stopped chat and an empty composer. Every answer in a multi-question form must be authorized before any answer is entered. Recognized approval cards permit only **Allow once**.

The app starts paused after restart. Saving settings pauses monitoring. Pause stops future checks after the current check; it does not cancel Codex's work or undo an action.

### 6. Activity

Inspect confirmed responses and actions here. Attempts are recorded before desktop interaction, then confirmed against the UI. An uncertain result pauses monitoring and blocks further relevant actions instead of automatically retrying.

Inspect and resolve the request in Codex or Chrome, then choose **Mark requests reviewed** in Monitor. Reviewing permits future requests; it does not resend the old request.

## Settings, updates, and troubleshooting

Settings, the latest 100 activity entries, and the permanent attempt journal are stored in `.local/state.json` inside your extracted folder. Keep this file private; it can contain chat titles, request text, replies, and standing instructions.

For an update: stop monitoring, disable and save Chrome actions, stop the server with Ctrl+C, back up `.local`, extract the new release, and copy `.local` into the new app folder before launching. Recreate the Windows virtual environment and reinstall its requirements. Reconnect the MCP registration if the installation path changed. Do not delete the old attempt journal to retry uncertain actions.

| Problem | What to do |
| --- | --- |
| `py`, `python3`, or `codex` is not found | Install the prerequisite, reopen your terminal, and restart Zenshin. |
| Codex cannot find its home or sign-in | Run in your normal user session outside a filesystem sandbox; verify `codex login status`. |
| Registered, but tools are missing in Codex | Reload MCP connections or restart Codex, then check discovery in the working chat. |
| A different/disabled Zenshin registration exists | Inspect `codex mcp get zenshin`. If you intend to replace it, run `codex mcp remove zenshin`, then connect again in the app. |
| Chrome action is disabled | Enable its toggle, select Send authorized replies in Monitor, and save. |
| No native password suggestion is available | Check Chrome's generation feature and the page's password fields. Zenshin stops on ambiguous fields or unsupported menus. |
| Chat or action is unconfirmed | Inspect it manually before marking requests reviewed. Do not repeat with a new request ID. |
| Port 8765 is in use | Stop the other Zenshin instance or launch with `--port 8766`, then register the tools for that port. |

For a different port or state location:

```sh
python3 app.py --port 8766 --state /path/to/state.json
```

On Windows, replace `python3` with `.\.venv\Scripts\python.exe` and use a Windows path.

## Verified scope and limitations

- On 16 October 2026, real Windows checks verified Codex connection, one delivered and acknowledged approval reply, and Zenshin-owned Chrome password generation/selection plus terms selection on a disposable form. Both password fields were filled and matched; terms was checked and marketing was left unchecked. No account was submitted and the final native Chrome check used no ChatGPT Computer Use.
- Earlier controlled tests verified Windows/Linux question forms, custom text, multi-question handling, draft preservation, and navigation on Windows. A real Linux file-access Allow once card was verified; real Windows approval cards and other command/tool-card variants still need live checks.
- Windows reply delivery previously encountered intermittent UI Automation event/confirmation errors. The latest single live reply passed; that does not establish that the intermittent issue is eliminated.
- Linux navigation can fail when Codex exposes an empty accessibility tree. Unrecognized labels or cards are left untouched. Browser-chat and dot monitoring are outside scope.
- This is an MVP that depends on the installed Codex/Chrome accessibility controls. Its scoped actions preserve normal permissions; broad standing instructions are not a guarantee of correct AI interpretation.

## Development and tests

Clone the repository instead of downloading an archive if you want to develop it:

```sh
git clone https://github.com/ahmedmurtazamalik/zenshin.git
cd zenshin
git checkout v0.2.0
```

Run the existing behavior tests with `python3 -m unittest -q`, or `.\.venv\Scripts\python.exe -m unittest -q` on Windows. The 61-test suite passed on Windows before this release. Tests using simulated desktop controls do not replace live UI verification. Read [AGENTS.md](AGENTS.md) before changing code.

[Older captioned walkthrough](demo/approval-helper-demo.mp4) · [Transcript](demo/README.md). This video predates Windows support, Chrome delegation, and the current onboarding UI.
