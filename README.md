# Zenshin

**Keep moving forward.** A local companion for Codex that answers authorized desktop requests and performs individual Chrome password and terms actions.

Zenshin runs on your computer with a dedicated Windows desktop window (or a browser control page when running from source). You choose what it may do. For Chrome actions, Zenshin itself focuses the password field, opens and selects Chrome's generated-password suggestion, or checks the named terms box through Windows accessibility. Codex requests the action and receives a result; ChatGPT Computer Use is not needed for those interactions.

## Windows release v0.2.8

[Download Windows installer](https://github.com/ahmedmurtazamalik/zenshin/releases/download/v0.2.8/Zenshin-Setup-0.2.8-windows-x64.exe) · [Release notes](https://github.com/ahmedmurtazamalik/zenshin/releases/tag/v0.2.8) · [Checksums](https://github.com/ahmedmurtazamalik/zenshin/releases/download/v0.2.8/SHA256SUMS.txt)

1. Run the installer. It installs for your Windows account without administrator access and adds a Start Menu shortcut. A desktop shortcut is optional.
2. Launch **Zenshin** from the Start Menu. The controls open in a dedicated desktop window, without a browser tab or console. Close the window to stop Zenshin.
3. For Chrome actions, choose **Connect Zenshin tools**, then reload MCP connections or restart Codex. Use **Copy Codex instructions** to paste the guidance into each working chat once, enable the Chrome actions you want, and save.
4. For chat monitoring, load and select chats, write narrow AI standing instructions, save, and choose **Start monitoring**. New settings use **AI** and **Send authorized replies**; monitoring starts paused and Chrome actions start disabled.

Python and accessibility dependencies are bundled. The installer checks for Microsoft WebView2 Runtime and installs it if missing; internet access is needed for that step. Use Windows 10 or later on x64. Codex desktop is required for chat monitoring; the signed-in Codex CLI is required for the Codex connection and AI decisions. Chrome is required for Chrome actions. The installation includes a setup guide with prerequisite, migration, and uninstall instructions.

The default installation is `%LOCALAPPDATA%\Programs\Zenshin`. Settings and the permanent attempt journal live in `.local/state.json` inside that folder. New settings default to **AI** and **Send authorized replies**. Upgrades preserve your saved choices. Use **Check for updates → Install update** in Connect to Codex. Zenshin downloads and checksum-verifies the installer, pauses monitoring, upgrades in place, reopens, and replaces an old MCP registration automatically. No uninstall is needed. Codex may need an MCP reload or restart afterward. Updates and uninstall preserve `.local`; uninstall through **Windows Settings → Apps**. To remove the Codex tool registration, run `codex mcp remove zenshin`.

To get this updater from v0.2.5 or earlier, close Zenshin and run the v0.2.8 installer once over the existing installation. Launch it from the installer to repair the old tool registration automatically. If updating manually later, re-run the installer; do not uninstall first.

When moving from a portable/source installation, stop it, copy its `.local` folder into the installed folder before launching, choose Connect Zenshin tools to replace the old registration. Do not run both installations together.

The [portable ZIP](https://github.com/ahmedmurtazamalik/zenshin/releases/download/v0.2.8/zenshin-windows-x64.zip) remains available: extract all files into a writable folder and launch `Zenshin.exe`. Keep `Zenshin-bridge.exe` beside it. Microsoft WebView2 Runtime must already be installed for portable use. Settings are stored beside the executable.

This is an unsigned application; Windows may display a publisher warning. It bundles Python bytecode, which can still be extracted or reverse engineered. The repository and release downloads are public. Linux uses the source setup below.

### Build in this repository

Run the **Windows release build** workflow from GitHub Actions (or push a version tag). It tests and builds on Windows x64, checks the portable executable, and verifies silent installation, Start Menu shortcut, installed-app startup/assets/settings/MCP, desktop-window rendering and normal close, reinstall preservation, and uninstall preservation. It uploads the installer, portable ZIP, and checksums as artifacts. Publishing a release is a separate step.

To build locally on Windows with Python 3.11 and Inno Setup 6 installed in its default location:

```powershell
python -m pip install -r requirements-windows.txt -r requirements-build.txt
.\build-windows.ps1
```

Outputs are in `dist/`. Native Codex/Chrome interactions still require a live Windows check. `Zenshin.exe --no-browser` runs the local server without a window; `--port` and `--state` work as in source mode.

## Source downloads v0.2.8

[Source ZIP](https://github.com/ahmedmurtazamalik/zenshin/archive/refs/tags/v0.2.8.zip) · [Source tar.gz](https://github.com/ahmedmurtazamalik/zenshin/archive/refs/tags/v0.2.8.tar.gz)

Both archives contain the same source for Windows and Linux, extracted into `zenshin-0.2.5`. They require Python and the Codex CLI; they do not contain the Windows executables or installer. Python 3.11 is the verified Windows build runtime. The release's `SHA256SUMS.txt` covers the Windows installer and portable ZIP, not these GitHub-generated source archives. macOS is not supported.

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

## Windows source setup

For the bundled app, use the installer or portable ZIP described above. To run from source:

1. Download the **Source ZIP** and choose **Extract All**. Work in the extracted `zenshin-0.2.5` folder, not inside the ZIP.
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

The Windows requirements install `uiautomation` (which installs `comtypes`) and `pywebview`. Source mode serves the browser control page; the packaged executable uses the desktop window. There is no frontend build. [Historical Windows implementation and live verification notes](WINDOWS.md) describe earlier versions; use this README for current setup.

## Linux source setup

Download the **Source tar.gz**, then extract and launch it:

```sh
tar -xzf zenshin-0.2.5.tar.gz
cd zenshin-0.2.5
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

The connected MCP server supplies usage instructions and tool descriptions. For consistent use, use **Copy Codex instructions** to paste the guidance once per working chat, alongside your task authorization; it does not need repeating for each action. Alternatively, save the guidance in the project's `AGENTS.md` for chats in that project. Registration alone does not authorize an action.

**Check connection** reports two separate things: whether the tools are registered, and whether Zenshin's chat-history connection responds. Registration does not prove that an existing Codex chat has loaded its tools. A disconnected chat-history connection does not prevent registered Chrome tools from working.

If registration fails, expand **Manual setup or troubleshooting** and use the command generated for your installation. Reconnect after moving Zenshin or changing its port.

### 2. Chrome actions — Windows

Enable **Allow Zenshin to select Chrome's suggested password**, **Allow Zenshin to check a named terms agreement box**, or both. In **Monitor**, ensure **Send authorized replies** is selected, then **Save changes**. Both action toggles are off for new settings.

- **Password:** Codex supplies the current page URL. Zenshin locates one visible new-password field, focuses it, invokes Chrome's native Suggest password command if needed, and selects the suggestion once. Chrome generates and fills the password. Confirmation/current/old-password fields are excluded from target selection. No password values are returned or logged.
- **Terms:** Codex supplies the current page URL and the exact checkbox label. Zenshin checks one matching, unchecked agreement box. Marketing opt-ins are excluded.

Zenshin performs these interactions using Windows UI Automation, without ChatGPT screenshots, coordinate clicks, or keyboard injection. The page must already be open and loaded. The individual actions do not open new Chrome windows, navigate, submit an account, solve CAPTCHA, or bypass a safety refusal or URL-policy stop.

Keep Zenshin running. These tools do not need selected chats or a running chat monitor. **Pause stops chat monitoring only.** To revoke Chrome actions, disable their toggles and save, or save **Preview only** mode.

For consistent use, paste the instructions from **Setup** once per Codex chat, alongside your task authorization, or save them in the project's AGENTS.md. You do not need to repeat the prompt for each action. Codex requests the action and supplies the current page URL; Zenshin performs it in Chrome. There is no manual URL field or site-opening/password button in the Chrome section.

### 3. Chats

Choose **Load Codex chats**, then select the conversations to monitor. Give each selected chat a unique title and keep only one visible copy. If a new chat is missing from the list, use **Add a chat by ID**.

**Check connection** here sends one read-only request through the existing Codex connection. If disconnected, choose **Load Codex chats** to reconnect. This connection reads identity/history; it does not control another client's approvals through internal IPC.

### 4. Authorization

New settings use **AI · follow my instructions**. Choose either:

- **AI · follow my instructions:** write narrow standing instructions, such as “Continue formatting this report. Ask me for missing facts or decisions outside that task.” AI examines recent context and the current request; missing facts and uncovered decisions stay for you.
- **Match exact questions:** save the complete expected question and its reply. Matching normalizes whitespace and otherwise requires the full question.

Changing the decision method switches the response mode to **Preview only**; select **Send authorized replies** again and save if you want delivery.

AI analysis uses your signed-in Codex CLI, times out after 60 seconds, and is canceled by Pause or changed settings. Invalid decisions and CLI failures stop monitoring without sending.

### 5. Monitor

New settings default to **Send authorized replies**. Write your AI standing instructions (or exact rules), select chats, and save before choosing **Start monitoring**. AI monitoring requires nonempty standing instructions. To inspect suggested chat replies before enabling delivery, choose **Preview only**, save, and start monitoring. Preview also blocks the Chrome tools. Upgrades retain your saved response and decision modes.

Keep the desktop window (packaged Windows app) or browser control page (source mode) open for five-second polling. Desktop mode visits selected chats one at a time. An ordinary reply requires a stopped chat and an empty composer. Every answer in a multi-question form must be authorized before any answer is entered. Recognized approval cards permit only **Allow once**.

The app starts paused after restart. Saving settings pauses monitoring. Pause stops future checks after the current check; it does not cancel Codex's work or undo an action.

### 6. Activity

Inspect confirmed responses and actions here. Attempts are recorded before desktop interaction. Chrome actions are confirmed against the UI; chat delivery is confirmed through the desktop controls or a newly echoed reply in chat history. An uncertain result pauses monitoring and blocks further relevant actions instead of automatically retrying.

Inspect and resolve the request in Codex or Chrome, then choose **Mark requests reviewed** in Monitor. Reviewing permits future requests; it does not resend the old request.

## Settings, updates, and troubleshooting

Settings, the latest 100 activity entries, and the permanent attempt journal are stored in `.local/state.json` beside the executable (packaged app) or `app.py` (source mode), unless you supply `--state`. Keep this file private; it can contain chat titles, request text, replies, and standing instructions.

Before updating, stop monitoring, disable and save Chrome actions, stop Zenshin, and back up `.local`.

- **Installer:** close the desktop window and run the new installer. It preserves `.local` and saved choices in the installation folder.
- **Portable ZIP:** close the desktop window, extract the new ZIP into a writable folder, and copy `.local` from the old folder before launching.
- **Source:** stop the server with Ctrl+C, extract the new source archive, and copy `.local` into the new folder before launching. Recreate the Windows virtual environment and install the new requirements.

Reconnect the MCP registration if the installation path or port changed. After updating, re-enable and save any Chrome actions you want. Do not delete the old attempt journal to retry uncertain actions.

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

For a different port or state location when running from source:

```sh
python3 app.py --port 8766 --state /path/to/state.json
```

On Windows, replace `python3` with `.\.venv\Scripts\python.exe` and use a Windows path. The packaged app accepts the same options, for example `Zenshin.exe --port 8766 --state C:\path\to\state.json`.

## Verified scope and limitations

- On 19 October 2026, the v0.2.8 Windows x64 release workflow passed all 63 tests in about 3 seconds, plus portable/installed-app startup, bundled assets, settings persistence, MCP discovery/transport, desktop-window rendering and normal close, reinstall, and uninstall checks. These packaging checks do not exercise live Codex or Chrome actions.
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
```

The clone follows the current default branch. To inspect the released source instead, run `git checkout v0.2.8`.

Install the source prerequisites above, then run the existing behavior tests with `python3 -m unittest -q`, or `.\.venv\Scripts\python.exe -m unittest -q` on Windows. The v0.2.8 suite contains 63 tests: all passed on Windows; the local Linux run passed with one Windows-only test skipped. Tests using simulated desktop controls do not replace live UI verification. Read [AGENTS.md](AGENTS.md) before changing code.

[Older captioned walkthrough](demo/approval-helper-demo.mp4) · [Transcript](demo/README.md). This video predates Windows support, Chrome delegation, and the current onboarding UI.
