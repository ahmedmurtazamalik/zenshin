# Codex Approval Helper build plan

Build a small local application that watches selected Codex chats and tasks, including a dot where accessible, and responds to approval requests covered by the user's standing authorization. Keep desktop automation, browser automation, and the Codex App Server connection in one app. Add them in stages and use one connection per conversation.

Follow the accompanying AGENTS.md. The app name is provisional.

## Implementation progress — 12 October 2026

13 October update: AI request interpretation is implemented using Codex CLI and standing instructions, with structured decisions, read-only preview, persistent decision reuse, cancellable analysis, and offered-choice desktop delivery. This replaces exact-wording requirements when AI mode is selected. Live CLI classification was verified; AI-driven desktop delivery has behavior tests but no new live end-to-end receipt. The existing demo predates this feature.

The local control window, App Server identity/history reading, AI classification, and Codex Linux desktop replies are implemented. Authorized live tests confirmed offered answers, custom text through GNOME keyboard input, a two-question form, and an AI-selected ordinary reply. Attempts are journaled before input, delivery is confirmed, duplicate replies are blocked, and uncertainty pauses monitoring. Browser and dot support are out of scope per user instruction. On 14 October, a captured file-access card exposed an alert-only detection bug. After supporting its Permissions heading, the normal AI/journal flow clicked Allow once, confirmed disappearance, and the controlled chat read the disposable file. Command and other tool-card variants still need live checks; command escalation is disabled by the test chat's policy.

## Outcome and assumptions

- First target: the user's Linux computer and existing signed-in account.
- Primary workflow: job applications interrupted by repeated permission requests, including submission and application consent checkboxes.
- The user selects conversations and authorizes specific action categories once. The app acts only within that scope.
- Handle one request at a time. A conversation has one active connection method.
- A chat message asking permission and an actual app approval control are different: respond to the relevant surface.
- Keep the app local, with one process, local settings, a small activity record, and a basic control window.

## Build sequence

| Step | Work | Completion check |
| --- | --- | --- |
| 1. Prove access | Inspect one desktop chat, one browser chat, and the dot's task view. Check whether App Server can access the relevant existing thread. Check built-in settings that may remove the user's repeated interruptions. | Read target identity and a pending request without sending anything. Record unavailable surfaces. |
| 2. Build the control window | Add selected conversations, explicit authorization rules, Start/Pause, and recent activity. Save settings locally. | Settings survive restart; the app starts paused. |
| 3. Complete one connection | Implement the method the access check proves best for the actual job-search chat. Initially show the detected request and proposed response before enabling automatic responses. | One covered request receives one response in the correct conversation. |
| 4. Add the remaining connections | Add App Server messaging and supported approval events, browser controls, and desktop controls using direct functions. Add dot support through its verified surface. | Each available method reads and answers a representative request. Report unsupported surfaces explicitly. |
| 5. Verify the workflow | Run a controlled job-application example with automatic responses enabled within the user's authorization. | Covered requests continue; uncovered requests stay pending; Pause prevents further responses. |

## Request handling

1. Confirm the selected conversation and read the complete pending request, rather than approving arbitrary text found on screen.
2. Check the request against explicit authorization rules and recognizable patterns.
3. Send the configured message or answer the actual approval control.
4. Record the request and result to prevent a second response, including after restart.

Ambiguous wording stays pending. A generic "yes" must not answer salary, eligibility, or other factual questions. Consent checkboxes must match an authorized category; do not infer that every checkbox is equivalent.

Recheck that the request is still pending before acting. If delivery has an uncertain result, pause that target instead of automatically switching methods or sending again. Start/Pause controls the helper's future responses; it does not stop already-running Codex work or undo a submission.

## Smallest implementation

Choose the language and desktop-control dependency after inspecting actual access. Browser automation can use Playwright if appropriate; use standard-library functionality where it is sufficient. Keep settings in a local file and use a small persistent record of handled requests. Prefer direct functions to classes, registries, or a plugin framework.

Use existing signed-in sessions and supported interfaces. Do not build credential extraction, edit Codex internal state to fabricate approvals, or attempt to override managed or built-in restrictions. Supported authorization and normal UI controls are the intended mechanisms.

The first version excludes cloud hosting, multiple accounts, an AI approval classifier, automatic connection switching, support for other operating systems, and job searching or application-form filling itself. The helper responds to Codex interruptions; Codex still performs the job-search work.

## Verification and stopping

Test only meaningful behavior: correct conversation, covered versus uncovered requests, duplicate prevention, restart behavior, and Pause. Use a small representative controlled example for each actual connection. Follow the ten-minute verification budget in AGENTS.md; after two substantially identical failures, diagnose and change approach or report the environmental blocker.

Completion means the supported connections work from one app and the selected job-search workflow continues within its authorized scope. An inaccessible desktop or dot surface remains a concrete blocker, not a completed integration. Do not substitute mock-only demonstrations for working integrations.

## Documentation findings

- Codex App Server exposes thread, turn, event, and supported approval operations. This does not prove that a separate client can control every existing desktop conversation or its pending approvals. [Official App Server documentation](https://learn.chatgpt.com/docs/app-server)
- Auto-review handles eligible tool approvals; Computer Use app approvals are a separate case. [Official auto-review documentation](https://learn.chatgpt.com/docs/sandboxing/auto-review)
- Dots support scoped custom rules such as "Take action without asking"; required confirmations and built-in safeguards remain. Check these settings before adding automation that duplicates them. [Official dot controls](https://learn.chatgpt.com/docs/dots/controls)
- Dot messaging is documented through ChatGPT and connected channels; a general external dot approval API has not been established in this conversation. [Official dot messaging documentation](https://learn.chatgpt.com/docs/dots/channels)

Recheck version-sensitive details before implementing. The access check determines the actual supported scope.
