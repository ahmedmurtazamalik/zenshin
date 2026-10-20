# Zenshin v0.2.12 — Fix Windows taskbar and Start Menu icons

- Install a permanent Zenshin icon file and assign it explicitly to Start Menu and desktop shortcuts.
- Give the app process and shortcuts the same stable Windows app identity so the taskbar associates the running window with the Zenshin shortcut.
- Keep the existing Zenshin artwork, updater, settings, and automatic action workflow.

# Zenshin v0.2.9 — Automatic AI workflow and action history

- Remove exact-question rules, Preview mode, and the Monitor section. AI sends authorized replies while monitoring runs.
- Add editable instruction presets for approvals, recommended choices, and continuing the existing plan. Existing nonempty instructions and the action journal are preserved.
- Connect installs reusable Codex guidance automatically, preserving other global instructions. New chats no longer need a copied setup prompt; refresh existing Codex sessions once.
- Start enables saved Chrome actions, including Chrome-only use without selected chats. Pause and Save stop further actions.
- Activity logs completed password selections, terms agreements, replies, and failed/skipped attempts. No manual review queue or global unconfirmed-action gate remains; duplicate requests are still not repeated.
- Errors stay visible without pulling the app back to another section. Chat-read timeout/progress and the update restart fix remain.

# Zenshin v0.2.8 — Fix restart after in-app updates

- Reset PyInstaller's inherited runtime when starting the installer and when the installer reopens Zenshin. The updated app extracts its own runtime instead of reusing the old app's deleted temporary folder.
- The installer also repairs this restart problem when an update is started by v0.2.6 or v0.2.7.
- Keep the Zenshin icon, saved settings, and existing MCP registration repair flow.
- If the previous update displayed a missing Python DLL error, dismiss it and launch Zenshin again. Then check for updates and install this release. No uninstall is needed.

# Zenshin v0.2.7 — Zenshin app icon

- The Windows executable, app window, Start Menu and desktop shortcuts, and installer now use the existing Zenshin logo.
- The icon includes sizes from 16 to 256 pixels for Windows display scaling.
- On v0.2.6, choose Check for updates, then Install update to upgrade in place. Settings and MCP registration repair use the existing update flow.

# Zenshin v0.2.6 — Visible chat reads and in-app updates

- Chat history reads wait up to 60 seconds and show a loading bar, elapsed time, and actual received bytes, including an explicit no-data-yet state.
- Check for updates and Install update download the latest Windows installer, verify its SHA-256 checksum, pause monitoring, upgrade in place, and reopen Zenshin.
- Installation replaces old or disabled Zenshin MCP registrations automatically. Connect Zenshin tools can also repair them directly; other MCP entries are preserved.
- Settings and the permanent attempt journal survive upgrades. Uninstalling before updating is unnecessary.
- From v0.2.5 or earlier, close Zenshin and run this installer once; launch from the installer to repair registration. Future releases can use the update button.
- Codex may still need an MCP reload or restart after an update. Automatic installation is available in the Windows desktop app; source installations can check release availability.

# Zenshin v0.2.5 — AI and authorized replies by default

- New settings default to AI decisions and Send authorized replies.
- Existing saved decision and response modes are preserved on upgrade.
- Monitoring still starts paused; Chrome action toggles remain unchanged.

# Zenshin v0.2.4 — Clearer Chrome action setup

- Chrome action toggles now name Zenshin as the app that performs password selection and terms checkbox actions. Codex requests each action through MCP and receives confirmation.
- Setup, Chrome actions, and the tour explain that the guidance prompt is pasted once per Codex chat, without repeating it for each action. Project instructions remain an alternative.
- Removed the manual registration URL field, Open and verify button, and manual password button. Codex supplies the current page URL with each MCP request.
- Chrome action execution and authorization behavior are unchanged.

# Zenshin v0.2.0 — Windows support and native Chrome actions

16 October 2026. MVP source release for Windows and Linux. Requires Python and a signed-in Codex CLI; no standalone executable or installer is bundled.

## Downloads

- [Windows source ZIP](https://github.com/ahmedmurtazamalik/zenshin/releases/download/v0.2.0/zenshin-v0.2.0-windows-source.zip)
- [Linux source tar.gz](https://github.com/ahmedmurtazamalik/zenshin/releases/download/v0.2.0/zenshin-v0.2.0-linux-source.tar.gz)
- [SHA-256 checksums](https://github.com/ahmedmurtazamalik/zenshin/releases/download/v0.2.0/SHA256SUMS.txt)

Both archives extract into `zenshin-0.2.0`. See the [README](README.md) for prerequisite, installation, onboarding, and update instructions. Archives exclude local settings, credentials, virtual environments, and test journals.

## New since v0.1.0

- Native Windows chat monitoring, question forms, custom text, multi-question forms, ordinary replies, and guarded one-time approval-card handling.
- Direct `select_chrome_password` and `check_chrome_terms` MCP tools. Zenshin owns the complete native Chrome interaction and returns a confirmed receipt directly to Codex.
- Zenshin now opens the password suggestion itself using native field focus and Chrome's Suggest password context-menu command. No ChatGPT Computer Use preparation, screenshots, coordinate clicks, or keyboard injection are needed for this action.
- Numbered sidebar, one-time Connect to Codex setup, generated manual registration command, live connection checks, and a first-visit/replayable tutorial.
- One persistent Windows UI Automation MTA worker, scoped site checks, durable action journals, and safe handling of uncertain outcomes.
- Retired global Chrome-preparation hooks and monitor-based browser handoffs. `codex_hook.py` remains an inert compatibility entry point for cached commands.

Existing Linux chat monitoring, exact rules, AI instructions, Preview, Start/Pause, draft protection, duplicate prevention, and activity history remain.

## Quick start

Windows, in the extracted folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-windows.txt
.\.venv\Scripts\python.exe app.py
```

Linux, in the extracted folder:

```sh
python3 app.py
```

Open http://127.0.0.1:8765. Follow Connect to Codex in the sidebar; enable only the actions you authorize. For chat monitoring, load chats, set authorization, and begin in Preview. Keep the server running and the control page open while monitoring.

## Verification and known limits

- The 61-test Windows behavior suite passed. The release ZIP was extracted and checked separately before publication.
- Real Windows Codex connection and one approval reply passed on 16 October; the chat acknowledged receipt.
- Zenshin-owned password generation/selection and terms selection passed on a disposable Chrome form. Both password fields matched; terms was checked and marketing stayed unchecked. No account was submitted or password values logged.
- Chrome actions require Windows, the intended page already open, one identifiable new-password field, and Chrome's native generation feature. They do not submit accounts or bypass safety or URL-policy stops.
- Pause stops chat monitoring only. Disable Chrome action toggles and save, or save Preview mode, to revoke direct actions.
- Historical Windows ordinary-reply confirmation failures remain a known intermittent issue despite the latest successful live reply.
- Real Windows Allow once cards and other command/tool-card variants remain unverified. Linux navigation needs readable accessibility contents and a fresh live verification. No fresh Linux desktop check was performed for this release.

The earlier [v0.1.0 Linux MVP](https://github.com/ahmedmurtazamalik/zenshin/releases/tag/v0.1.0) remains available.
