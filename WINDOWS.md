# Windows development handoff

The **v0.1.0 Linux MVP prerelease is Linux-only**. This is the plan for continuing development on a Windows device; it does not add Windows support or a Windows installer.

## Start on the Windows device

Use native Windows for the first port: a native Codex desktop app, native Codex CLI, and native Python. Keep the checkout in a normal Windows directory such as `C:\Users\your-name\source\zenshin`. WSL uses a separate Codex home by default, so mixing a WSL CLI with the native desktop app adds another environment to diagnose. See the [official Windows setup documentation](https://learn.chatgpt.com/docs/windows/windows-app).

Install Git, Python 3, the Codex desktop app, and the Codex CLI. Sign into the desktop app and CLI on that device. Then open PowerShell:

```powershell
git clone https://github.com/ahmedmurtazamalik/zenshin.git
Set-Location zenshin
git switch -c codex/windows-support
py -3 --version
codex --version
Get-Command codex -All
```

The branch is optional but keeps Windows work separate from the released Linux version. Read `AGENTS.md` and `README.md` before editing. There is no frontend build or pip dependency list to install in the current Linux version. Windows desktop dependencies should be chosen after inspecting the real controls.

Do not expect `py -3 app.py` to provide working Windows monitoring yet. In particular, connecting to Codex currently uses a Linux-compatible pipe reader that needs to change.

## Keep these parts

Keep `index.html`, the themes and assets, settings format, AI decision rules, exact matching, response journal, duplicate prevention, and progress UI. `ai_decision.py` should retain the same read-only classification behavior. `app.py` should retain its read-only App Server operations and serialized settings/reply operations.

The separate App Server reads chat identity and history; it does not own another desktop client's live permission requests. Sending approval responses still requires inspecting and operating the actual desktop controls.

Keep `linux_ui.py` working for Linux users. A small OS choice between `linux_ui` and a new `windows_ui` module is enough; a provider framework or UI rewrite is unnecessary.

## 1. Make preview mode work

Start with the shared Python code before implementing desktop responses:

- **Subprocess reading:** `app.py:rpc` calls `select.select()` on the App Server's stdout pipe. On Windows, Python's `select` supports sockets, not subprocess pipes. Replace this with a Windows-compatible reader while preserving complete newline-delimited JSON messages, the ten-second response timeout, and the existing EOF/error handling. See [Python's `select` documentation](https://docs.python.org/3/library/select.html).
- **CLI launching:** both `app.py:connect` and `ai_decision.py:start` launch `codex` directly. Check what `Get-Command codex -All` resolves on this machine, and confirm Python can launch the installed CLI. Handle the actual executable or shim used by that installation without introducing a general launcher system.
- **Text encoding:** state files, AI output, schema files, and error logs currently use some default-encoding file operations. Make text exchanged with Codex explicitly UTF-8 where needed, and verify a chat/instruction containing non-ASCII text.
- **Paths:** keep using `pathlib` and temporary directories. Use a separate test state rather than modifying the user's real response-attempt journal.

After these fixes:

```powershell
py -3 app.py --port 8766 --state .local/windows-test-state.json
```

Open `http://127.0.0.1:8766`, connect, and confirm the inventory contains chats from the native desktop environment. Select a harmless test chat. Start in **Preview only**, first with an exact rule and then with AI standing instructions. Confirm Zenshin reads the selected chat and produces a decision without typing or clicking in Codex.

This is the first milestone: native Windows can list/read chats and preview AI decisions. It does not require UI Automation yet.

## 2. Prove desktop controls are readable

Use a Windows UI Automation inspection tool on a harmless Codex test chat before writing the full response implementation. Inspect the real controls for:

- The displayed chat title and the conversation document.
- A question with offered answers and a custom-answer field.
- The ordinary composer and its Send button.
- A real one-time permission card, including its text, Deny, and Allow once controls.

Record which controls expose names, text, and supported actions. Windows UI Automation provides patterns such as Invoke, Value, and Selection; availability depends on the actual control. See [Microsoft's control-pattern documentation](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controlpatternsoverview).

If Codex exposes an empty or incomplete tree, stop and diagnose that first. Do not implement coordinate-based clicking against controls that have not been identified. Do not assume Windows labels, roles, or card structure match the Linux accessibility tree.

## 3. Implement the small Windows desktop module

Match the functions already consumed by `app.py:poll_desktop`:

| Function | Required behavior |
| --- | --- |
| `open_chat(thread_id, name, on_open=None)` | Open the selected chat when necessary; wait for and verify its displayed document. |
| `pending(name, question)` | Match the actual live question form. |
| `conversation_pending(name, text)` | Confirm the latest assistant message is visible and an ordinary reply can be entered. |
| `approval_cards(name)` | Return live card text and the offered one-time response. |
| `answer(name, question, response, next_question=None, on_progress=None)` | Choose or enter an answer, advance/submit correctly, and confirm the result. |
| `reply(name, text, response, on_progress=None)` | Preserve drafts, enter/read back an ordinary reply, submit, and confirm its echo. |
| `approve(name, text, response, on_progress=None)` | Re-read the same card, activate only `Allow once`, and confirm disappearance. |

Use a simple platform import in `app.py` and route these existing calls through it. Start with one offered answer before implementing all paths. Use UI Automation actions for named controls; add a keyboard fallback only if a reproduced input limitation requires it. The Linux GI/AT-SPI and Mutter RemoteDesktop implementation does not carry over to Windows.

Preserve the current protections: selected-chat identity and unique titles, rejection of multiple visible copies, no overwriting drafts, every question authorized before entering a multi-question form, attempts saved before actions, no retry after uncertain delivery, and Pause on failure. Persistent permission grants must remain excluded. Progress callbacks should report real opening/sending/confirming work.

## 4. Add chat switching

Windows must replace Linux's `xdg-open` launcher. A direct `os.startfile()` call can ask Windows to open the same `codex://threads/<thread-id>` link, provided the installed Codex app has registered that scheme. See the [Codex deep-link reference](https://learn.chatgpt.com/docs/reference/commands#deep-links).

A successful launcher call is not proof that the selected chat loaded. Keep the current sequence: check whether the correct chat is already displayed, launch if needed, wait with a deadline, verify the displayed title/document, then inspect requests. Visit selected chats one at a time. If arrival cannot be verified, pause without responding. Preview-only mode should continue without navigating.

## 5. Verify, then package

Run the existing suite as the first baseline:

```powershell
py -3 -m unittest -v
```

Two known test portability points need attention: `test_app.py` also uses `select` on the server subprocess's stdout, and several tests use `/nonexistent-approval-helper-test-state` as an absent-state fixture. Replace the latter with isolated `TemporaryDirectory` paths where needed. Update desktop mocks to use the selected module, keeping the Linux-specific behavior tests on Linux. Do not treat a skipped Windows test as proof of working desktop interaction.

Use isolated state and a harmless local test chat for live verification, in this order:

1. One offered answer, then a custom text answer and a complete multi-question form.
2. An ordinary continuation reply with an empty composer; confirm an existing draft is preserved.
3. A real file-access `Allow once` card, then command and other tool cards if the test chat's policy permits them to appear.
4. Start with another chat displayed; verify navigation, two selected chats in sequence, and failure without sending when the target cannot be confirmed.
5. Confirm Pause, progress updates, duplicate prevention, and the unconfirmed-attempt behavior after restarting.

A denied operation that never displays a permission card is not a successful approval test. Keep tests local and reversible; do not use an external workflow as the first experiment.

Only after these paths work should you add a double-click launcher and consider an executable/installer. Choose packaging around the dependencies actually used by the proven Windows implementation. Re-run the Linux suite before merging shared-code changes, and document which Windows version and Codex/CLI versions were actually tested.

## What the Linux release has verified

The Linux suite has 26 tests and runs in about one second. Controlled live tests have verified offered answers, custom text, multiple questions, ordinary replies, and one real file-access `Allow once` approval. Settings were preserved by using isolated test journals.

Automatic chat switching has regression coverage, but its latest live check was blocked by Codex exposing no readable accessibility contents. The launcher returned success; arrival could not be confirmed, so monitoring paused without sending. Actual command-escalation and other tool-card variants still need live verification. These are existing Linux verification gaps, not completed Windows features.

## First prompt for Codex on Windows

> Read AGENTS.md, README.md, and WINDOWS.md. Continue the Windows port on this native Windows device. First inspect Python, Codex CLI resolution, and the repository, then implement only the preview-mode milestone: a Windows-compatible App Server pipe reader, any required native CLI launch fix, and UTF-8 handling for real inputs. Preserve Linux behavior, read-only App Server scope, the journal, and serialized operations. Run the narrow relevant tests, then verify chat listing/reading and one AI preview using isolated state. Do not implement desktop responses or package an installer yet. Report the concrete result and any actual blocker.
