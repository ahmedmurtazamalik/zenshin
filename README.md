# Codex Approval Helper

A local Linux app for reducing repeated Codex permission interruptions. It reads chat identity and history through Codex App Server and can answer **question forms and ordinary continuation requests in the Codex desktop app** through normal Linux accessibility controls.

[Watch the captioned video walkthrough](demo/approval-helper-demo.mp4). [Transcript and chapter guide](demo/README.md). The walkthrough shows real app screens using separate demo settings; no new approval is sent during recording.

## Run

```sh
python3 app.py
```

Open http://127.0.0.1:8765. Requires Python 3 and a signed-in `codex` CLI. Desktop mode also requires the system Python `gi` package and AT-SPI. On GNOME Wayland, keyboard fallback also uses a temporary Mutter RemoteDesktop session; these were already installed on the tested machine. No pip packages or frontend build are needed. Run outside a filesystem sandbox that prevents Codex from initializing its own runtime or accessing the desktop accessibility bus.

1. Connect to Codex and select chats. If a new chat is missing, add its thread ID; the app reads its actual title.
2. Give selected chats unique titles, and keep the chat you want answered open in a Codex window. Multiple visible copies are rejected.
3. Choose **AI analysis with Codex CLI** and write standing instructions describing what the helper may approve or continue. Alternatively, keep **Exact question rules** for the existing deterministic behavior.
4. Choose **Read-only preview** first, or **Answer authorized desktop requests** to enable scoped responses, then Start monitoring.

The app starts paused after restart. Saving changes pauses monitoring. Keep the control window open for its five-second polling. Pause stops future checks after the current check. One response is handled per check. It does not stop Codex work or undo actions.

Optional: `python3 app.py --port 8766 --state /path/to/state.json`.

## Response behavior

AI mode reads the latest eight user/assistant messages plus the request and offered choices. It runs a separate, ephemeral `codex exec` in a read-only temporary directory using the existing CLI sign-in. Its structured decision is `approve`, `continue`, `needs_input`, or `no_response`, with a proposed response and reason. The CLI is instructed not to use tools; any observed tool use causes its decision to be discarded. Conversation content is treated as data, not authorization to expand the standing instructions.

Start in **Read-only preview** to inspect decisions. For example: “Continue formatting this report within my existing instructions. Ask me for missing personal information or a new decision.” You do not need to predict the question's wording. Empty standing instructions cannot start AI monitoring. Existing saved exact-rule settings retain their behavior until you switch methods.

An unchanged request, recent context, and instruction set reuse a saved decision, including after restart. New context or changed instructions trigger a new analysis. Calls consume Codex model usage and require working CLI authentication and model access; they are not local/offline inference. Analysis runs without blocking the HTTP server, times out after 60 seconds, and is canceled by Pause or changed settings. Invalid results and CLI failures pause monitoring without sending.

In AI desktop mode, only `approve` or `continue` can send. Offered answers use their live controls; other authorized responses use guarded text input. Every question in a multi-question form must have an authorized answer before any answer is entered. The attempt journal and delivery confirmation apply to the whole form. AI interpretation can be wrong: use narrow standing instructions and inspect preview decisions before enabling desktop responses.

Preview mode reads the latest assistant message without sending anything. Historical messages are not proof of a pending request.

Desktop mode checks structured questions from the newest turn against the live question form. Exact rules match the complete question, normalizing whitespace. Offered choices advance to the next question or submit the last answer immediately; the helper never clicks Send afterward. Custom answers preserve existing drafts, enter text, read it back, then use Next or Send.

Ordinary replies require the newest recorded assistant message to be visible, Codex to have stopped, no pending question form, and an empty composer. The helper reads the response back before Send and confirms a new echoed reply. Messages that cannot be matched to visible controls remain previews.

Chromium on this Wayland machine rejects accessibility text editing. After explicit user approval, a GNOME RemoteDesktop keyboard fallback was verified. It creates a temporary session, focuses the selected empty field, checks focus while typing, and stops the session afterward. Keyboard fallback supports single-line responses. Input or confirmation failures preserve the draft and pause monitoring; the helper never retries an uncertain attempt.

Settings, the latest 100 activity entries, preview fingerprints, and a permanent response-attempt journal are stored in `.local/state.json`. Attempts are saved atomically **before** UI actions. An interrupted or unconfirmed attempt pauses monitoring and blocks that chat after restart. Inspect and resolve the request in Codex, then use **I reviewed the unconfirmed requests**. Reviewed requests still cannot be sent again automatically; future requests can be monitored.

Desktop documents expose chat titles rather than thread URLs. The app checks selected IDs and titles against App Server and rejects known duplicate titles and multiple visible copies. Keep titles unique. It does not switch chats automatically.

## Verified scope and remaining work

On 12 October 2026, Codex CLI 0.159.3 successfully read existing chats. A separate App Server reported desktop threads as `notLoaded`; its managed daemon socket was absent. App Server is therefore used for identity/history, not to claim control over another client's live approval events.

The default AT-SPI cache initially returned null window children. Reading the fresh accessibility tree exposed the actual desktop question controls. A separately created controlled chat received `Yes, mark the local test complete.` and reported that the local test was approved. No job application or external action was performed. The first confirmation check paused after submission because it expected a separate Send step; the corrected immediate-choice behavior is covered by a regression test.

Newly created desktop chats may be readable by ID before the standard inventory includes them; the app supports adding such chats directly.

**Approval-dialog implementation:** Desktop mode now detects the installed app's approval cards by their alert header and Deny/Allow once controls. It supplies all accessible card text and the one-time option to the existing AI classifier, or matches that complete text against an exact rule. Only the exact response `Allow once` can activate the card; persistent permission grants are excluded. The attempt is saved first, the card is re-read before clicking, and disappearance in the same chat confirms the UI response. This confirms the approval response, not successful execution of the command or tool. Normal chat replies are blocked while an approval card is visible.

**Remaining verification:** This path is implemented and unit-tested against the installed UI structure, but has not received a real pending command/file/tool card on this machine. The controlled command test auto-ran under auto-review; with Ask for approval selected, escalation was disabled. An in-workspace file test ran directly; an external-workspace file test was rejected without a dialog. A separate read-only App Server still does not own the desktop client's requests. A real pending card is needed for end-to-end verification. Different labels or card structures are left untouched. Browser-chat and dot support were explicitly removed from scope by the user.

Read-only preview continues to show recorded messages; approval cards are read in desktop mode. To inspect a live card without authorizing it, use desktop AI mode with standing instructions such as “Do not approve anything; leave every request for me.”

No credentials are extracted, internal approvals fabricated, or managed restrictions changed. Protocol reference: [official Codex App Server documentation](https://learn.chatgpt.com/docs/app-server).

## Verify

```sh
python3 -m unittest -v
```

The 20 tests cover matching, target identity, Pause, persistence, draft preservation, AI classification handling, attempts saved before delivery, duplicate prevention, uncertain delivery, multi-question authorization, ordinary reply journaling, one-time approval restrictions, pre-action persistence, and changed-card/navigation failures. The suite runs in about 0.03 seconds.

On 13 October 2026, authorized live tests in “Approval Helper controlled test” confirmed an AI-selected offered answer, a custom free-text answer using GNOME input, a complete two-question form under one attempt, and an AI-selected ordinary composer reply. These used isolated journals in `/tmp`; the user's monitoring settings were preserved. The existing demo video predates AI mode and these additional desktop paths.
