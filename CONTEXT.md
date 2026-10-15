# Codex Approval Helper continuation context

## Current scope — 15 October 2026

The global Chrome-preparation hooks and toggle have been retired. The original Codex approval/form features and individual Chrome helpers remain. The user requested cleanup only; the future direct single-action integration is not implemented. Use PLAN.md and README.md for current scope and limits. The dated handoff notes below are historical.

Handoff saved on 12 October 2026, using the user's Asia/Karachi date. Read AGENTS.md and PLAN.md before continuing.

## User request

The user wants to reduce repeated interruptions during Codex job searches. Codex often asks permission to submit an application, accept application terms or consent checkboxes, or take another job-related action even after the user has given permission for future actions.

They proposed an automated clicker or a program that sends "yes, approved" to Codex chats, tasks, and the dot. They asked whether desktop automation, browser automation, and direct Codex integration could all be included in one application. The agreed direction was one local application with all three methods, built incrementally.

The user provided /home/murtaza/Documents/AGENTS.md and asked for a simple build plan using it. The accompanying AGENTS.md is an exact copy of that file. These are engineering instructions; they are not a separate request to expand the product's scope.

The user then said, "Okay, start building the app." Before implementation began, they interrupted and requested that the plan and context be saved under $HOME/Murtaza/[app name], creating the directory if needed. They intend to create/open a Codex project folder there and continue implementation from that location.

## Current state

- On 13 October 2026, added `ai_decision.py` and an AI/exact-method selector with standing instructions. AI analyzes eight recent conversational messages and the request using ephemeral read-only `codex exec` with a structured output schema and existing CLI auth. Classifier calls are polled without blocking the control server and canceled by Pause/settings changes. Decisions persist by request/context/instructions fingerprint. AI desktop delivery only accepts an authorized offered choice on a live single-question card; ordinary messages and custom suggestions are previewed only. Fifteen tests pass. Two harmless real CLI tests classified authorized continuation and missing salary information correctly; no new desktop response was sent. Git was previously initialized on main with 60 granular commits and a captioned demo under `demo/`; that video predates AI mode.

- First build created in this directory on 12 October 2026: `app.py`, `index.html`, `test_app.py`, and `README.md`. No third-party dependencies.
- Run `python3 app.py` and open http://127.0.0.1:8765. The window supports real local chat discovery, selected targets, saved exact request/response rules, Start/Pause, message previews, and persistent activity history.
- Desktop single-question responses are now implemented in `linux_ui.py`. App Server remains read-only; the actual response uses the question card's offered choice through Linux AT-SPI. The UI provides a saved preview/desktop mode.
- The app starts paused. Desktop attempts are durably recorded before UI actions, confirmed by a new echoed answer and disappearance of the pending card, and never retried automatically. Unconfirmed attempts pause monitoring; the user can mark them reviewed after resolving them manually. Preview fingerprints remain separate from delivered-response records.
- Codex CLI 0.159.3 successfully initialized a separate App Server and listed existing chats. Existing desktop threads were `notLoaded`; no threads were loaded in that server. The default managed daemon control socket was absent.
- The Linux accessibility library is installed. A fresh AT-SPI tree (`Cache.NONE`) exposes Codex's real controls even though the tool-based native surface was unavailable. Keep selected chats open with unique titles. Offered choices submit immediately; Send is for custom text and is not used by this connection.
- The user authorized creating a test chat. Created `01a12fa1-a968-79c0-b282-4c338b2c29f8`, titled `Approval Helper controlled test`. It was opened in a separate normal Codex window. The helper activated its harmless offered response `Yes, mark the local test complete.` once; the chat confirmed receipt. The initial confirmation logic paused because it expected a separate Send step; that logic was corrected and regression-tested. No real application or other external action was performed.
- The test chat is readable by ID but was absent from the standard App Server inventory. The UI now supports Add chat by ID.
- Custom-answer logic now preserves drafts, reads filled text back before Send, and pauses on failed editing. It is unit-tested but not verified for live delivery: AT-SPI editing returns false for this Chromium contenteditable UI, and synthetic keyboard events do not enter text in this Wayland session. Empty entries expose embedded-object characters and placeholder sections; `entry_text` reads their rendered text. Automatic approval review rejected creating a GNOME RemoteDesktop keyboard session as a privileged desktop-input boundary; approval was requested and no session was created. Do not invoke that API without approval or work around the rejection.
- Desktop monitoring now displays a latest-message preview when no live single-question card is found, without sending a reply. Eleven tests pass. Remaining unsupported surfaces: browser/dot requests, ordinary free-text replies, multi-question cards, and command/file/other tool approval dialogs. See README.md.

## Decisions already made

- Keep all three connection methods within the same app, but add them in stages.
- Scope the first version to one Linux computer, an existing signed-in account, and job-application approvals.
- Let the user select targets, define standing authorization, and start or pause monitoring.
- Use one active connection method per conversation and handle requests sequentially.
- Distinguish a conversational permission question from an actual approval dialog or event. Sending "yes" in chat may not resolve a separate app-level request.
- Use explicit authorization and recognizable patterns first. Do not add an AI classifier unless a demonstrated requirement makes it necessary.
- Record handled requests and pause on uncertain delivery instead of sending again through a different connection.
- Keep local settings and a small activity record. Avoid a framework, service architecture, queue, or provider registry.
- Do not treat broad permission as authorization to invent factual application answers or approve every possible request.

## Findings and unresolved questions

Official documentation was read when planning. Relevant links are in PLAN.md. App Server supports threads, messages, and approval events, but integration with the user's existing desktop threads and their active approvals is unverified. Dot custom rules may eliminate some interruptions, but a general external dot approval API was not established.

Discovery findings are recorded above and in README.md. A real pending desktop question is verified; browser/dot and other approval types still need samples and supported access. Do not confuse persisted assistant messages with live permission requests.

No real-world approval samples have been collected, so the initial matching rules cannot yet be finalized. Read-only inspection should establish which interruption types are actually stopping the user's workflow.

## Next action

Continue from the desktop question connection under AGENTS.md. Verify a representative remaining browser/dot or other approval surface before adding its response path. Do not enable sending merely because a historical message matches a saved rule. The corrected desktop confirmation path has unit coverage and the offered-choice submission has a real receipt; another harmless live question can verify the whole corrected flow when authorized.

Before changing code, state the concrete outcome, material assumptions, smallest approach, exclusions, and an observable verification check as required by AGENTS.md. The user has already requested implementation; do not restart with another generic planning or permission question. Ask only when an unresolved choice materially changes the outcome or authorization scope.

The user has now requested implementation in this project. The older handoff request is historical context.

## 13 October desktop completion

User explicitly approved GNOME RemoteDesktop keyboard sessions and harmless prompts in Approval Helper controlled test. Keyboard fallback verified; Reply… fields supported. Multi-question forms authorize all questions first, offered answers advance immediately, and one journal entry covers the form. Ordinary composer replies require a visible latest message, stopped chat, no pending form, empty draft, readback and echoed delivery. Real AI offered-choice and ordinary-reply paths passed. Seventeen unit tests pass. Browser chat is excluded (Codex only); dot skipped per user instruction. Tool approval dialogs still need a supported live surface. Existing video predates these changes.

## Approval-dialog implementation awaiting live verification

Added accessibility detection of the installed approval card (alert header + Deny/Allow once), complete-card AI/rule authorization, one-time-only submission, recheck and disappearance confirmation, and the existing durable attempt journal. Twenty tests pass. Installed UI source was inspected read-only to establish the card structure; internal IPC was not used. Actual test dialogs remain unavailable: auto-review ran the command; Ask for approval disabled escalation; an in-workspace file patch ran directly; an outside-workspace patch was rejected without a prompt. Asked the user to leave a real command/file/tool card pending. Do not claim live approval verification yet. Preview mode still reads history; desktop mode reads approval cards. The temporary stricter controlled-test setting was restored to its original Approve for me value.

## 14 October: Allow once file-access approval verified

The user authorized another controlled-chat test after earlier attempts failed. With Approval Helper controlled test visible and on Ask for approval, request_permissions produced a real turn-only read request for .local/zenshin-card-capture-probe.txt. Its captured tree had Deny/Allow once buttons and a static Permissions heading, with no alert role. A regression case reproduced the alert-only detector failure; linux_ui.approval_forms now accepts this heading as well as an alert. The normal AI/journal flow then clicked Allow once, confirmed disappearance, and recorded sent. The controlled chat read the marker zenshin-card-capture-probe. Evidence: /tmp/zenshin-live-card-capture.json and /tmp/zenshin-verified-approval-qaj4tppp/state.json. All 21 tests pass in 2.138 seconds. User monitoring settings were untouched. Command escalation remains policy-disabled; other command/tool card variants are not yet live-verified. Do not repeat the old popup experiments or ask the user to approve the test card manually.

## 14 October: automatic chat navigation

The user approved visiting selected chats sequentially. Desktop monitoring now calls linux_ui.open_chat before inspecting each target. It leaves an already displayed chat alone, otherwise opens codex://threads/<ID> with xdg-open and waits up to ten seconds for the unique chat document. Failure pauses before inspection or delivery; preview-only mode does not navigate. The UI reports Opening chat in Codex. All 26 tests pass in 0.868 seconds, including sequential visits, load/skip, timeout, and no-send failure behavior.

Live check used /tmp/zenshin-navigation-check.py with an isolated state and no reply rules. xdg-open succeeded, but AT-SPI exposed Codex frames with null child contents, so the first chat could not be confirmed and monitoring paused without any response attempts. GNOME toolkit-accessibility and org.a11y.Status flags were originally false; temporarily enabling them did not expose contents in the running app. Original settings were restored and the root chat link reopened. Do not claim live navigation is verified. No Codex restart was attempted during this active chat. User settings/journal were preserved.
