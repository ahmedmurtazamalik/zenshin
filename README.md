# Codex Approval Helper

A local Linux app for reducing repeated Codex permission interruptions. It reads chat identity and history through Codex App Server and can answer **single-question cards in the Codex desktop app** through normal Linux accessibility controls.

[Watch the captioned video walkthrough](demo/approval-helper-demo.mp4). [Transcript and chapter guide](demo/README.md). The walkthrough shows real app screens using separate demo settings; no new approval is sent during recording.

## Run

```sh
python3 app.py
```

Open http://127.0.0.1:8765. Requires Python 3 and a signed-in `codex` CLI. Desktop mode also requires the system Python `gi` package and AT-SPI; both were already installed on the tested machine. No pip packages or frontend build are needed. Run outside a filesystem sandbox that prevents Codex from initializing its own runtime or accessing the desktop accessibility bus.

1. Connect to Codex and select chats. If a new chat is missing, add its thread ID; the app reads its actual title.
2. Give selected chats unique titles, and keep the chat you want answered open in a Codex window. Multiple visible copies are rejected.
3. Choose **AI analysis with Codex CLI** and write standing instructions describing what the helper may approve or continue. Alternatively, keep **Exact question rules** for the existing deterministic behavior.
4. Choose **Read-only preview** first, or **Answer matching desktop questions** to enable scoped responses, then Start monitoring.

The app starts paused after restart. Saving changes pauses monitoring. Keep the control window open for its five-second polling. Pause stops future checks after the current check. One response is handled per check. It does not stop Codex work or undo actions.

Optional: `python3 app.py --port 8766 --state /path/to/state.json`.

## Response behavior

AI mode reads the latest eight user/assistant messages plus the request and offered choices. It runs a separate, ephemeral `codex exec` in a read-only temporary directory using the existing CLI sign-in. Its structured decision is `approve`, `continue`, `needs_input`, or `no_response`, with a proposed response and reason. The CLI is instructed not to use tools; any observed tool use causes its decision to be discarded. Conversation content is treated as data, not authorization to expand the standing instructions.

Start in **Read-only preview** to inspect decisions. For example: “Continue formatting this report within my existing instructions. Ask me for missing personal information or a new decision.” You do not need to predict the question's wording. Empty standing instructions cannot start AI monitoring. Existing saved exact-rule settings retain their behavior until you switch methods.

An unchanged request, recent context, and instruction set reuse a saved decision, including after restart. New context or changed instructions trigger a new analysis. Calls consume Codex model usage and require working CLI authentication and model access; they are not local/offline inference. Analysis runs without blocking the HTTP server, times out after 60 seconds, and is canceled by Pause or changed settings. Invalid results and CLI failures pause monitoring without sending.

In AI desktop mode, only `approve` or `continue` can send, and the response must match an offered choice on a live single-question card. The live chat/card is checked again after analysis through the normal polling and delivery path. Missing information, uncovered requests, ordinary conversational replies, and custom-text suggestions remain visible without automatic delivery. The attempt journal and delivery confirmation still apply. AI interpretation can be wrong: use clear, narrow standing instructions and inspect preview decisions before enabling desktop responses.

Preview mode reads the latest assistant message without sending anything. Historical messages are not proof of a pending request.

Desktop mode requires both a recorded structured question in the selected thread and its matching live question card in that chat's accessible desktop document. It matches the full question, normalizing whitespace only. Unmatched questions remain pending. When no live single-question card is found, the latest message is displayed as a preview without sending anything.

In the tested Codex version, activating an offered choice submits it immediately. The helper activates that choice once and confirms that the card disappears and a new answer is echoed in the same chat. It does not click Send afterward.

Custom responses have a guarded implementation: preserve existing drafts, fill the custom-answer field through its accessibility editing interface, read it back, and activate Send only if the live question and response still match. Failed editing pauses monitoring. On this machine, Chromium's contenteditable fields report embedded objects and reject AT-SPI edits; synthetic AT-SPI keyboard events do not insert text in the Wayland session. Custom delivery therefore remains unverified and blocked here. A GNOME RemoteDesktop keyboard-input test requires approval after automatic approval review rejected creating that session. No compositor-control session was created.

Settings, the latest 100 activity entries, preview fingerprints, and a permanent response-attempt journal are stored in `.local/state.json`. Attempts are saved atomically **before** UI actions. An interrupted or unconfirmed attempt pauses monitoring and blocks that chat after restart. Inspect and resolve the request in Codex, then use **I reviewed the unconfirmed requests**. Reviewed requests still cannot be sent again automatically; future requests can be monitored.

Desktop documents expose chat titles rather than thread URLs. The app checks selected IDs and titles against App Server and rejects known duplicate titles and multiple visible copies. Keep titles unique. It does not switch chats automatically.

## Verified scope and remaining work

On 12 October 2026, Codex CLI 0.159.3 successfully read existing chats. A separate App Server reported desktop threads as `notLoaded`; its managed daemon socket was absent. App Server is therefore used for identity/history, not to claim control over another client's live approval events.

The default AT-SPI cache initially returned null window children. Reading the fresh accessibility tree exposed the actual desktop question controls. A separately created controlled chat received `Yes, mark the local test complete.` and reported that the local test was approved. No job application or external action was performed. The first confirmation check paused after submission because it expected a separate Send step; the corrected immediate-choice behavior is covered by a regression test.

Newly created desktop chats may be readable by ID before the standard inventory includes them; the app supports adding such chats directly.

**Still unimplemented:** browser-chat and dot connections, ordinary free-text conversational replies, multi-question forms, and command/file/other tool approval dialogs. Custom-response logic exists but live delivery is blocked as described above. Only the helper's localhost page is available through the browser-control tool; no signed-in browser/dot request or supported shared App Server event connection was available. Each needs an observed request and delivery surface before implementation. This is a working first desktop connection, not completion of all three methods in PLAN.md.

No credentials are extracted, internal approvals fabricated, or managed restrictions changed. Protocol reference: [official Codex App Server documentation](https://learn.chatgpt.com/docs/app-server).

## Verify

```sh
python3 -m unittest -v
```

The 15 tests cover exact matching, target selection, Pause, persistence, attempts recorded before delivery, duplicate prevention, uncertainty, omitted chat inventory entries, custom draft preservation, AI decision reuse, context input, missing-information decisions, unsupported choices, invalid model output, and cancellation. On 13 October 2026, two real CLI classification checks returned `continue` with the offered option for an authorized formatting request and `needs_input` with no response for a salary question. A full browser-to-CLI preview check correctly returned `no_response` for the controlled chat's completed action, displayed its reason, reused one persisted result across polls, and paused successfully. No new live AI-driven desktop approval was sent. The earlier desktop test used a real Codex question; unit tests do not send approvals.
