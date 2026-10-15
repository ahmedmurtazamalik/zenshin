# Zenshin: individual browser-action handoff

Status: cleanup only. The direct action integration described here is not implemented.

## Scope to preserve

Keep Codex chat monitoring, exact rules, AI standing instructions, question-form answers, ordinary replies, Allow once cards, saved settings, Pause, draft protection, and the durable attempt journal. Keep the existing native Chrome password/terms helpers, site checks, and persistent Windows MTA worker.

The mandatory Chrome-preparation toggle, global lifecycle hooks, browser-call interception, and per-chat preparation state are retired. Optional standalone Chrome checks remain. The existing monitor-based browser handoff remains provisional until replaced; its Windows continuation is not reliable.

## Next implementation, when requested

1. Codex uses its normal browser tools and existing permission flow first.
2. For a capability limitation, Codex explicitly requests one supported Zenshin action: accept Chrome's suggested password for the current site, or check a specific terms agreement checkbox.
3. A small direct tool interface calls the existing helper. Verify the requested site and user's enabled action, journal before acting, confirm once, and return a result to the calling Codex turn. Do not require a typed continuation message for that handoff.
4. A safety refusal or URL-policy stop remains a stop. Missing facts, ambiguous controls, or uncertain activation require review. Do not read or return passwords, submit accounts, or accept marketing opt-ins.

Do not build a website navigator, signup orchestrator, generic action framework, refusal-wording detector, or another global pre-tool hook. Do not add scaffolding or new tool endpoints until implementation is requested.

## Verification

Prove each action independently on a disposable page using only password-presence/match and checkbox flags. Prove the caller receives the actual action result and can continue. Preserve tests for original Codex approvals/forms, site scope, preview/Pause, and duplicate prevention. A full website signup sequence is not required to establish either action.

The existing Windows ordinary-reply delivery-confirmation bug is separate work; do not claim it is solved by this cleanup. Follow the verification budget in AGENTS.md.
