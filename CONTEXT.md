# Codex Approval Helper continuation context

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
