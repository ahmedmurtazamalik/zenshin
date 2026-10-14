# Zenshin on Windows

This checkout implements native Windows preview and desktop modes. The published v0.1.0 archive remains Linux-only; use this checkout for Windows. No executable or installer is bundled.

## Setup and run

Use native Windows Python, the Codex desktop app, and a signed-in Codex CLI. From the project directory:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-windows.txt
.venv\Scripts\python.exe app.py
```

Open http://127.0.0.1:8765. The app starts paused. Connect, select chats with unique titles, save exact rules or AI standing instructions, and begin with Preview only. Enable Send authorized replies when the instructions cover the work you want continued. Keep the control page open for polling.

Run the app in a normal user session with the desktop unlocked. A filesystem sandbox may prevent the CLI from finding its signed-in home or accessing desktop controls. WSL is useful for Linux tests; run the Windows app and CLI natively.

## Included

- Preview mode, exact-question rules, AI decisions, saved settings, activity, themes, and progress use the same control page and shared logic as Linux.
- Desktop mode opens selected chats through `codex://threads/<ID>`, verifies their displayed documents, and visits them sequentially.
- Question forms support offered choices, custom text, and multiple questions. Every answer must be authorized before a multi-question form is entered.
- Ordinary continuation replies require a stopped chat, its latest message visible, and an empty composer.
- Recognized approval cards include their full context and permit only `Allow once`. Persistent permission grants are excluded.
- Attempts are saved before responding, confirmed from the live UI, and never retried automatically. An uncertain result pauses monitoring and blocks that request after restart. Review unconfirmed requests only after inspecting them in Codex.

The Windows module uses the `uiautomation` package and its `comtypes` dependency. Text uses ValuePattern; actions use InvokePattern or SelectionItemPattern. No coordinate clicks or keyboard fallback are needed for the controls tested here. The installed Codex Store package identifies its executable as `ChatGPT.exe`; Zenshin checks the `OpenAI.Codex` package path as well as the chat document, rather than relying on that executable label alone.

The App Server stays read-only for identity/history. Windows pipe readiness uses `PeekNamedPipe`; Linux keeps its existing `select` path. CLI launching prefers `codex.exe` and supports the installed npm Node entry point when needed. State and AI files are explicitly UTF-8. `linux_ui.py` is unchanged.

## Verified on 14 October 2026

Environment: Windows 10 build 19045, Python 3.11.3, Codex desktop package 26.1007.2314.0, Codex CLI 0.162.0-alpha.17.2, and uiautomation 2.0.29.

The isolated “Zenshin Windows test” chat verified:

- Native App Server connection, chat listing/history, and a read-only AI preview with Unicode input.
- An offered answer delivered once and recorded as sent.
- A custom answer containing café, Urdu text, and literal `{Enter}` text.
- An offered first answer and custom second answer in one journaled form.
- An AI-authorized ordinary reply, with echoed delivery confirmation.
- Preservation of an existing composer draft.
- Opening selected chats in sequence and confirming arrival from a worker thread.
- Preview, AI, Start/Pause, and repeated desktop checks through the HTTP server on separate request threads.

Two reproduced Windows issues are fixed and regression-tested: Chromium includes an empty field's placeholder in its accessible value, and Send can succeed before Invoke reports an event-subscriber error. The latter never triggers a second Invoke; successful confirmation still requires a new echoed response.

The complete suite passes on native Windows (33 tests, 2.109 seconds) and Ubuntu through WSL (33 tests, 1.218 seconds):

```powershell
.venv\Scripts\python.exe -B -m unittest -v
```

## Remaining live verification

A real Windows approval card could not be produced in the controlled chat. No permission-request tool was available; the one command-escalation test completed automatically under Approve for me. Neither result proves the card was operated. Card-context detection, one-time-only authorization, and changed-card rejection have behavior coverage, but file, command, and other tool-card variants still need live verification when such a card is actually available. Approval settings and managed restrictions were preserved.

The older demo is a Linux walkthrough and predates AI mode and these Windows tests. Browser-chat and dot support remain outside the agreed product scope.
