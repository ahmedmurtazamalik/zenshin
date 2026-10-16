# Zenshin on Windows

Zenshin v0.2.0 includes native Windows preview and desktop modes. Download the Windows source ZIP from the [release page](https://github.com/ahmedmurtazamalik/zenshin/releases/tag/v0.2.0) and follow the [installation and onboarding guide](README.md). No executable or installer is bundled. The older v0.1.0 archive remains Linux-only.

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

## Current limits and verification

Windows UI Automation calls run on one persistent MTA worker, with its cached client released on that thread at server shutdown. This replaces the unsuccessful per-request COM cache-reset workaround. No matching native crash recurred during the latest 20-minute check. HTTP progress remains readable during a desktop operation.

The original form and navigation features have the live evidence above. Ordinary chat replies are currently unreliable: Send may succeed before an accessibility event error, and confirmation can still fail. Windows operation of a real Allow once card and other command/tool-card variants remain unverified.

The individual Chrome password and terms actions passed earlier browser-side live tests. The failed monitor-based handoff has now been replaced with two explicit MCP tools that return results directly to Codex, without navigating Codex or typing continuation replies. Saved action toggles, Preview protection, standalone manual checks, site guards, and the attempt journal remain. The terms tool requires an exact checkbox label. Global preparation hooks and per-chat preparation bookkeeping remain retired; see [setup and operation](README.md#chrome-assistance-on-windows) and [verification scope](PLAN.md).

On 15 October the direct-action version passed 56 tests on Windows (4.105 seconds) and Ubuntu/WSL (2.602 seconds, one Windows-only server test skipped). A real Codex CLI session called both tools, received receipts, and continued through normal approval review using a simulated desktop backend. Native Chrome clicks were not rerun for that integration check. The global MCP entry was added without changing approval settings; existing sessions may need their MCP connection reloaded.

Historical crash, URL-detector, and handoff evidence is preserved in `.local/chrome-url-diagnostics-2026-10-15.json`, `.local/chrome-restart-e2e-result.json`, and `.local/chrome-mta-e2e-result.json`. See [Chrome usage and limits](README.md#chrome-assistance-on-windows).

The older demo is a Linux walkthrough. This checkout supports Windows; the published v0.1.0 archive remains Linux-only. Browser-chat and dot support remain outside the agreed scope.

On 16 October, a direct app test on a disposable local Chrome form verified that Zenshin itself focuses the new-password field, opens Chrome's native Suggest password menu, selects the generated password, and checks the named terms box. Both password fields were filled and matched, terms was checked, and marketing remained unchecked. No ChatGPT Computer Use tools, keyboard injection, screenshots, or coordinate clicks were used. The action still requires the intended page to be open, one identifiable new-password field, and Chrome's generation feature to be available. Evidence: `.local/native-owned-result.json`.
