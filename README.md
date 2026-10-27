# Zenshin

**Keep moving forward.** A local companion for Codex that answers authorized desktop requests and performs individual Chrome password and terms actions.

Zenshin runs on your computer with a dedicated Windows desktop window (or a browser control page when running from source). You choose what it may do. For Chrome actions, Zenshin identifies controls by meaning, focuses the password field, opens and selects Chrome's generated-password suggestion, or checks the agreement box through Windows accessibility. Codex requests the action and receives a result. The Codex CLI may analyze supplied text or screenshots and return structured decisions; Zenshin captures screenshots and performs every click and text entry through its own native code. Zenshin never delegates computer interaction to ChatGPT/Codex Computer Use or browser-use tools.

## Windows release v0.2.21

[Download Windows installer](https://github.com/ahmedmurtazamalik/zenshin/releases/download/v0.2.21/Zenshin-Setup-0.2.21-windows-x64.exe) · [Release notes](https://github.com/ahmedmurtazamalik/zenshin/releases/tag/v0.2.21) · [Checksums](https://github.com/ahmedmurtazamalik/zenshin/releases/download/v0.2.21/SHA256SUMS.txt)

1. Run the installer. It installs for your Windows account without administrator access and adds a Start Menu shortcut. A desktop shortcut is optional.
2. Launch **Zenshin** from the Start Menu. The controls open in a dedicated desktop window, without a browser tab or console. Close the window to stop Zenshin.
3. Choose **Connect Zenshin tools** to register the tools and install reusable Codex guidance. Reload MCP connections or restart Codex once, enable the Chrome actions you want, save, and choose **Start monitoring**.
4. For chat replies, load and select chats, choose or edit an AI instruction preset, save, and choose **Start monitoring**. Monitoring starts paused and Chrome action switches start disabled.

Python and accessibility dependencies are bundled. The installer checks for Microsoft WebView2 Runtime and installs it if missing; internet access is needed for that step. Use Windows 10 or later on x64. Codex desktop is required for chat monitoring; the signed-in Codex CLI is required for the Codex connection and AI decisions. Chrome is required for Chrome actions. The installation includes a setup guide with prerequisite, migration, and uninstall instructions.

The default installation is `%LOCALAPPDATA%\Programs\Zenshin`. Settings and the permanent attempt journal live in `.local/state.json` inside that folder. AI decisions and authorized replies are always enabled while monitoring runs. Upgrades preserve your instructions, action switches, and journal. Use **Check for updates → Install update** in Connect to Codex. Zenshin downloads and checksum-verifies the installer and pauses monitoring. Leave **Finish update and reconnect Codex (restarts Codex)** selected on the final installer page. Finish reopens Zenshin, repairs tool registration and guidance, quits and relaunches Codex to refresh its MCP connections, reconnects chat history, and restores monitoring if it was running. Running Codex work will be interrupted by the restart. No separate reconnect or MCP reload is needed. Updates and uninstall preserve `.local`; uninstall through **Windows Settings → Apps**. To remove the Codex tool registration, run `codex mcp remove zenshin`.

To get this updater from v0.2.5 or earlier, close Zenshin and run the v0.2.15 installer once over the existing installation. Launch it from the installer to repair the old tool registration automatically. If updating manually later, re-run the installer; do not uninstall first.

When moving from a portable/source installation, stop it, copy its `.local` folder into the installed folder before launching, choose Connect Zenshin tools to replace the old registration. Do not run both installations together.

The [portable ZIP](https://github.com/ahmedmurtazamalik/zenshin/releases/download/v0.2.21/zenshin-windows-x64.zip) remains available: extract all files into a writable folder and launch `Zenshin.exe`. Keep `Zenshin-bridge.exe` beside it. Microsoft WebView2 Runtime must already be installed for portable use. Settings are stored beside the executable.

This is an unsigned application; Windows may display a publisher warning. It bundles Python bytecode, which can still be extracted or reverse engineered. The repository and release downloads are public. Linux uses the source setup below.

### Build in this repository

Run the **Windows release build** workflow from GitHub Actions (or push a version tag). It tests and builds on Windows x64, checks the portable executable, and verifies silent installation, Start Menu shortcut, installed-app startup/assets/settings/MCP, desktop-window rendering and normal close, reinstall preservation, and uninstall preservation. It uploads the installer, portable ZIP, and checksums as artifacts. Publishing a release is a separate step.

To build locally on Windows with Python 3.11 and Inno Setup 6 installed in its default location:

```powershell
python -m pip install -r requirements-windows.txt -r requirements-build.txt
.\build-windows.ps1
```

Outputs are in `dist/`. Native Codex/Chrome interactions still require a live Windows check. `Zenshin.exe --no-browser` runs the local server without a window; `--port` and `--state` work as in source mode.

## Source downloads v0.2.15

[Source ZIP](https://github.com/ahmedmurtazamalik/zenshin/archive/refs/tags/v0.2.15.zip) · [Source tar.gz](https://github.com/ahmedmurtazamalik/zenshin/archive/refs/tags/v0.2.15.tar.gz)

Both archives contain the same source for Windows and Linux, extracted into `zenshin-0.2.5`. They require Python and the Codex CLI; they do not contain the Windows executables or installer. Python 3.11 is the verified Windows build runtime. The release's `SHA256SUMS.txt` covers the Windows installer and portable ZIP, not these GitHub-generated source archives. macOS is not supported.

## What it does

- Answers offered choices, custom text, multi-question forms, ordinary continuation requests, and recognized one-time approval cards in selected Codex desktop chats.
- Follows editable AI standing instructions through your signed-in Codex CLI, with ready-to-use approval and continuation presets.
- Offers Start/Pause, saved settings, progress, action history, and a durable attempt journal that prevents duplicate delivery.
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

Choose **Connect Zenshin tools** to register this installation's MCP bridge and install a marked Zenshin guidance block in Codex's global instructions. Other instructions and MCP entries are preserved. Reconnecting refreshes the guidance and repairs old registrations.

Reload MCP connections or restart Codex once to load the registered tools. Global guidance and MCP tool descriptions remain available automatically. While monitoring, Zenshin also sends the current Chrome-action setup directly into each selected chat, so you do not have to paste reminders into existing chats.

**Check connection** checks tool registration and chat-history access separately. Chrome tools do not need the chat-history connection. Manual registration troubleshooting remains available if the CLI cannot be found or registration fails.

### 2. Chrome actions — Windows

Enable password selection, terms agreement, or **Solve CAPTCHAs using Codex AI**, save, then choose **Start monitoring**. No selected chat is required for Chrome-only use. Start and the switches provide standing authorization for Codex to request those actions while Zenshin runs. **Pause** blocks further Chrome actions and chat checks; saving settings also pauses them.

Selected chats receive one setup message naming the currently enabled and disabled Chrome actions. Changing those switches queues an updated message for each selected chat after monitoring starts again, including when all actions are disabled. Zenshin remembers confirmed delivery across restarts and deselecting/reselecting a chat. It waits while a chat is running, an approval or question is pending, or a composer draft is present. Messages are journaled before sending, confirmed from the live chat or its persisted history, and never automatically repeated after an uncertain send. These are instructions to Codex, rather than a technical lock on its tool choice.

- **Password:** Codex supplies the current page URL. Zenshin identifies the new-password field from its label and surrounding text, opens and selects Chrome's native suggestion, and verifies that field stayed filled. Unrelated password fields do not have to be filled. No password values are returned or logged.
- **Terms:** Codex supplies the current page URL and optionally a wording or intent hint. Zenshin identifies the unchecked agreement box by meaning; an exact label is not required. Terms bundled with marketing consent are allowed. Separate marketing, cookie, CAPTCHA, and age-only boxes are excluded.
- **CAPTCHA:** When requested, Codex calls `solve_chrome_captcha`. Zenshin sends a cropped screenshot of an identifiable, visible CAPTCHA frame/container to your existing signed-in Codex CLI, applies bounded challenge clicks or answer text, and checks for visible successful verification. No external solver account or API key is required. This uses your Codex model allowance. The switch starts disabled. Invisible risk checks, drag puzzles, and challenges without an identifiable container are unsupported. Attempts stop after 90 seconds or 12 steps; unconfirmed actions are journaled and not repeated. Visible widget success does not guarantee the website's eventual server-side acceptance.

Password and terms actions use your signed-in Codex CLI to interpret labels and nearby static text, including unfamiliar wording or languages. Editable values and native password-suggestion labels are never sent to the classifier. Controls and the site are checked again before activation; ambiguous selections stop without clicking. Classification can take up to 60 seconds.

Chrome must display the intended page in its selected tab; loading it in a background tab is not sufficient. These actions do not navigate, submit accounts, or bypass a safety refusal or URL-policy stop. CAPTCHA images are temporary and deleted after the action; answer text is not included in Activity receipts. Confirmed actions are logged immediately without a review step. After updating the source, choose **Connect Zenshin tools** and reload MCP connections to discover the new tool.

### 3. Chats

Choose **Load Codex chats**, then select the conversations to monitor. **Start monitoring** authorizes Zenshin to send their automatic Chrome-action setup/update messages as well as covered replies. Selected chats need unique titles. If a new chat is missing from the list, use **Add a chat by ID**. Chat history reads allow up to 60 seconds and show elapsed time and received data. A failure stays visible without changing the section you selected; load chats again to reconnect.

### 4. Authorization

Choose **Approve task requests**, **Use recommended choices**, or **Continue existing plan**, then edit the prefilled instructions as needed. AI uses recent chat context to send authorized replies automatically. Exact-question matching and Preview mode have been removed.

Keep the control window open for its five-second checks. Chat replies require a live response control in the selected chat. Missing facts are not invented: requests that cannot be answered are logged as skipped rather than entering a review queue. AI analysis uses your signed-in Codex account, times out after 60 seconds, and is canceled by Pause or changed settings.

### 5. Activity

Activity is a history of Chrome-action setup messages, password selections, terms agreements, chat replies, and failed or skipped attempts. It has no approval or review controls. The journal records attempts before desktop interaction and prevents the same request from being sent twice. An unconfirmed result is recorded and is not repeated; independent later requests can continue without clearing a review gate.

## Settings, updates, and troubleshooting

Settings, the latest 100 activity entries, and the permanent attempt journal are stored in `.local/state.json` beside the executable (packaged app) or `app.py` (source mode), unless you supply `--state`. Keep this file private; it can contain chat titles, request text, replies, and standing instructions.

Use **Check for updates → Install update** for an in-place update, then the installer's **Finish update and reconnect Codex** option. Refresh failures stay visible and paused. The first upgrade from v0.2.16 or earlier reconnects selected chats but remains paused because those versions did not record the previous monitoring state; subsequent upgrades preserve it.

- **Installer:** close the desktop window and run the new installer. It preserves `.local` and saved choices in the installation folder.
- **Portable ZIP:** close the desktop window, extract the new ZIP into a writable folder, and copy `.local` from the old folder before launching.
- **Source:** stop the server with Ctrl+C, extract the new source archive, and copy `.local` into the new folder before launching. Recreate the Windows virtual environment and install the new requirements.

Reconnect the MCP registration if the installation path or port changed. After updating, check your saved switches and choose Start monitoring. Do not delete the old attempt journal to retry uncertain actions.

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

- For v0.2.21 on 27 October 2026, all 121 behavior tests passed in 4.4 seconds. Chrome readiness now selects the active native page among additional documents and reports the condition preventing readiness. CAPTCHA capture waits for native foreground focus. A controlled local CAPTCHA was solved and confirmed through Zenshin. Google and hCaptcha demos passed readiness but remained unconfirmed at solving: Google's challenge changed during analysis; hCaptcha exposed no visible controls or verification success to the solver. No challenges were retried and no accounts or forms were submitted.
- For v0.2.20 on 26 October 2026, all 119 behavior tests passed in 5.6 seconds. The update reconnect now tolerates desktop controls disappearing during Codex shutdown and waits for process exit before reopening it. The packaged app passed startup, bundled assets, settings persistence, and MCP discovery/transport checks. A live Codex restart remains unverified.
- For v0.2.18 on 23 October 2026, all 115 behavior tests passed in 4.1 seconds. A reproduced shutdown race could abort the update reconnect before reopening Codex when Windows briefly had no foreground window. The restart now tolerates that transition and reopens through the registered Windows launcher. Native-control tests verify the race, activation failures, and new-process confirmation; live quit/reopen still needs user verification.
- For v0.2.19 on 23 October 2026, all 118 behavior tests passed in 5.4 seconds. Setup delivery now remains pending if a chat or composer becomes unavailable before typing, and automatically recovers the pre-write composer failure recorded by v0.2.18. A live native test sent the setup to the selected dummy chat, confirmed exactly one copy in persisted history, and verified that reloading the journal did not resend it. Existing guards still prevent repeats after unconfirmed typing or sending.
- For v0.2.16 on 23 October 2026, all 100 behavior tests passed in 4.4 seconds. Automatic selected-chat setup, settings updates, restart/reselection persistence, draft protection, and delivery confirmation were tested with simulated native controls. CAPTCHA behavior also has simulated-control tests; real public CAPTCHA solving and live delivery of the automatic setup message still need user verification.
- For v0.2.15 on 22 October 2026, all 83 behavior tests passed in 3.9 seconds. Five native Chrome actions passed on four public sites: password filling on Overleaf and LOA Portal, offscreen terms on OpusGo and LOA Portal, and bundled terms plus email/WhatsApp/SMS consent on PrivateCircle. Separate marketing boxes stayed unchecked. No accounts were submitted or password values read. The live checks used the updated source through Zenshin MCP; release packaging has separate Windows smoke checks.
- On 20 October 2026, all 72 Windows behavior tests passed in about 4 seconds. The v0.2.13 release workflow checks portable/installed-app startup, bundled assets, settings persistence, MCP discovery/transport, desktop-window rendering and normal close, update restart, old bridge process and pipe closure, fresh bridge startup, icons, reinstall, and uninstall. These packaging checks do not exercise live Codex or Chrome actions.
- Five planned live Chrome cases passed both password and terms actions through Zenshin MCP on the first attempt: 10 actions with no retries in 71 seconds. Password actions took 7.0–8.4 seconds and terms actions took 3.4–4.5 seconds. Both password fields stayed filled and matched; terms stayed checked and marketing stayed unchecked. These results cover the disposable local form used for testing.
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

The clone follows the current default branch. To inspect the released source instead, run `git checkout v0.2.21`.

Install the source prerequisites above, then run the existing behavior tests with `python3 -m unittest -q`, or `.\.venv\Scripts\python.exe -m unittest -q` on Windows. Tests using simulated desktop controls do not replace live UI verification. Read [AGENTS.md](AGENTS.md) before changing code.

[Older captioned walkthrough](demo/approval-helper-demo.mp4) · [Transcript](demo/README.md). This video predates Windows support, Chrome delegation, and the current onboarding UI.
