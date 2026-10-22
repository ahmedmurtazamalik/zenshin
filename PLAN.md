# Zenshin: individual browser-action handoff

Status: the direct individual-action MCP integration is implemented.

## Scope to preserve

Keep Codex chat monitoring, exact rules, AI standing instructions, question-form answers, ordinary replies, Allow once cards, saved settings, Pause, draft protection, and the durable attempt journal. Keep the existing native Chrome password/terms helpers, site checks, and persistent Windows MTA worker.

The mandatory Chrome-preparation toggle, global lifecycle hooks, browser-call interception, and per-chat preparation state are retired. Optional standalone Chrome checks remain. The former monitor-based browser handoff and its typed continuation have been replaced by direct tool results.

## Implemented behavior

1. Codex uses its normal browser tools and existing permission flow first.
2. For a capability limitation, Codex explicitly calls `select_chrome_password` or `check_chrome_terms` with the current site, a stable request ID, and optionally a terms wording or intent hint. The existing Codex classifier identifies password fields and agreement boxes from their labels and nearby static text rather than exact wording.
3. `zenshin_mcp.py` calls the running app's `/api/browser-action`. For passwords, Zenshin itself focuses the new-password field, opens Chrome's native suggestion through Windows UI Automation, and selects it; no ChatGPT Computer Use preparation is required. It requires the saved action toggle and Send authorized replies mode, checks the current page without navigation, journals before acting, confirms once, and returns a receipt to the same turn. Direct actions work without chat monitoring. Pause stops monitoring; action toggles revoke tool authorization. Confirmed request IDs replay receipts; uncertain attempts block future Chrome actions until reviewed.
4. A safety refusal or URL-policy stop remains a stop. Missing facts, ambiguous controls, or uncertain activation require review. Do not read or return passwords or submit accounts. Terms bundled with marketing consent are allowed; separate marketing boxes remain excluded.

No website navigator, signup orchestrator, generic action framework, refusal-wording detector, or global pre-tool hook is needed. Chrome actions currently use Windows UI Automation; the original approval/form features remain supported on Windows and Linux.

## Verification

Behavior tests cover both action receipts through a real stdio process and local HTTP endpoint, journal-before-action, retries, optional terms hints, bundled consent, semantic control selection, disabled/Preview controls, and uncertain activation. Existing approval/form, site, draft, and Pause regressions remain. A real Codex client can verify discovery and turn continuation using a simulated native backend; this does not establish a new live Chrome result. Browser-side live verification uses presence and checkbox flags, never password values. A full signup sequence is unnecessary.

The existing Windows ordinary-reply delivery-confirmation bug remains separate work. The individual-action result does not use that path. Follow the verification budget in AGENTS.md.
