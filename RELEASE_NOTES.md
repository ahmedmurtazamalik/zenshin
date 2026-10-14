# Zenshin v0.1.0 — Linux MVP

14 October 2026. Prerelease; Linux source distribution, with no bundled Python runtime or desktop dependencies. Windows support is not implemented in this release.

## Included

- Local control page with selected Codex chats, saved instructions, preview mode, Start/Pause, activity history, themes, and live check progress.
- AI interpretation through the signed-in Codex CLI, plus exact-question rules. AI can approve, continue, or leave requests for the user.
- Desktop offered answers, custom text, multi-question forms, ordinary replies, and one-time approval-card handling.
- Durable attempts recorded before sending, duplicate prevention, draft preservation, and a pause when delivery cannot be confirmed.
- Automatic navigation to selected chats through their Codex links, checking chats sequentially and waiting for the correct chat before inspecting requests.

## Run on Linux

Download `zenshin-v0.1.0-linux-source.tar.gz` from the release assets, then:

```sh
tar -xzf zenshin-v0.1.0-linux-source.tar.gz
cd zenshin-0.1.0
python3 app.py
```

Open http://127.0.0.1:8765. Requires Python 3, a signed-in native `codex` CLI, and working desktop accessibility. Desktop control uses the system Python `gi` package and AT-SPI; the keyboard fallback uses GNOME Mutter RemoteDesktop. There are no pip dependencies or frontend build steps for the Linux version. The app starts paused. Begin with Preview only and narrow standing instructions; keep the control page open for polling.

## Verified behavior and known limitations

- The 26 automated tests pass on Linux in about one second. Offered choices, custom text, multi-question answers, ordinary replies, and a real file-access `Allow once` approval have live verification from controlled tests.
- Automatic chat navigation is implemented and regression-tested, but its latest live check could not confirm arrival: the running Codex app exposed empty accessibility contents. It paused without sending. Navigation still needs a live check with readable accessibility contents.
- Command-escalation and other tool-card variants still need live verification. The controlled chat's policy rejected command escalation before showing a dialog. Managed restrictions are not overridden.
- Selected chats need unique titles. Multiple visible copies of the same chat are rejected. Desktop automation requires an unlocked desktop with readable controls; it is not a headless service.
- Browser chats and dots are outside the current scope. The included older demo predates AI mode and the newer desktop paths.

## Continue development on Windows

The [Windows development handoff](https://github.com/ahmedmurtazamalik/zenshin/blob/v0.1.0/WINDOWS.md) is committed in this release and included in its source archive. `WINDOWS.md` is also attached as a separate release asset. It covers native Windows setup, the current portability blockers, the smallest implementation sequence, and the live checks required before claiming Windows support.

Clone the project on the Windows device and start a development branch:

```powershell
git clone https://github.com/ahmedmurtazamalik/zenshin.git
cd zenshin
git switch -c codex/windows-support
```

Read `AGENTS.md` and `WINDOWS.md` before implementing. The first milestone is working Windows preview mode and one harmless, confirmed question response. The Linux source archive is not a Windows installer.
