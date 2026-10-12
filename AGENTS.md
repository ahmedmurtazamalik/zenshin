# MVP Engineering Contract

This project is a small MVP for a handful of trusted users. Optimize for a working product, short feedback loops, and code a developer can understand in one sitting. Do not optimize for hypothetical scale, enterprise completeness, or impressive architecture.

These instructions apply to planning, implementation, review, refactoring, and testing. If another project document proposes a more elaborate design, treat it as historical context unless the user explicitly asks to preserve it.

## Governing rule

Implement the smallest clear change that satisfies the user's stated outcome. Every added file, dependency, abstraction, configuration option, validation branch, and test must be justified by a current requirement or a reproduced failure.

Before changing code, state:

1. The concrete outcome.
2. Assumptions that materially affect the implementation.
3. The smallest viable approach.
4. What will deliberately not be built.
5. A short verification command or observable check.

Ask only when ambiguity would materially change the result. Otherwise choose the simplest reversible interpretation and proceed.

## Simplicity rules

- Prefer a direct function over a class, framework, service, registry, factory, strategy, adapter, or plugin system.
- Do not abstract single-use code. Extract only after real duplication makes the result easier to read.
- Do not add layers for possible future providers, tenants, platforms, scale, or reuse.
- Do not add dependencies when a short use of existing code or the standard library is adequate.
- Do not add caches, queues, background workers, retries, concurrency, distributed coordination, or observability systems without a measured current need.
- Do not add configuration switches unless the user needs both behaviors now.
- Prefer deleting or consolidating unnecessary code over rearranging it behind new interfaces.
- Match the repository's current style. Do not reformat, rename, document, type, or refactor adjacent code unless required.
- Every changed line must trace to the requested outcome.
- When 50 clear lines can replace 200 indirect lines, prefer 50 clear lines.

## Reality-based engineering

Design for the declared users, data volume, deployment, and threat model—not an imagined enterprise version.

- Handle normal inputs and failures that can realistically occur in the current product.
- Do not handle impossible states merely because they can be imagined.
- Do not add compatibility code for unsupported platforms or versions.
- Do not implement speculative security hardening. Preserve essential protections for credentials, authentication, authorization, destructive actions, and untrusted input, but do not turn a small internal tool into a security program.
- Record a genuine concern briefly instead of implementing it when it is outside the stated threat model.

## Testing contract

Tests exist to protect behavior, not to maximize count or coverage.

- Add a test only for a user-visible requirement, a reproduced bug, a meaningful boundary, or a realistic failure with material impact.
- Do not test language/runtime/library behavior, impossible combinations, private implementation details, trivial getters, cosmetic markup, or speculative attacks.
- Prefer one representative behavior test over a matrix of near-duplicates.
- For a bug, first reproduce it with the smallest test when practical, then fix it.
- For a refactor with unchanged behavior, rely on the smallest relevant existing tests; do not create a parallel test suite.
- Do not add snapshot, fuzz, property, load, stress, concurrency, cross-platform, or end-to-end tests unless explicitly requested or justified by an observed failure.
- Do not chase coverage percentages.
- Run the narrowest relevant check while iterating. Run the full suite once at the end only when its runtime is reasonable.
- Never let verification loop indefinitely. After two substantially identical failures, diagnose the cause and change approach. If the remaining blocker is environmental or external, report it plainly and stop.
- Default verification budget: 10 minutes total unless the user explicitly authorizes a longer run. State what was and was not verified when the budget expires.

## Refactoring and simplification

When asked to simplify:

1. Measure or identify the actual pain: runtime, startup, build, test duration, code size, duplication, or maintenance burden.
2. Establish a baseline with the cheapest reliable measurement.
3. Rank candidates by evidence and expected payoff.
4. Make one coherent simplification at a time.
5. Preserve current user-visible behavior unless the user explicitly approves removing it.
6. Delete obsolete code and tests made redundant by the change.
7. Re-measure and keep only changes that make the system demonstrably simpler or faster.

Do not perform a wholesale rewrite, framework migration, schema redesign, or dependency replacement merely because it could be cleaner. Propose such a change separately with evidence.

## Scope and stopping

Do not expand the task while working. Keep a short parking-lot note for unrelated findings; do not fix them.

Stop when the requested behavior works and the smallest relevant verification passes. Do not continue polishing, adding defenses, expanding tests, or preparing for hypothetical future requirements.

At completion, report only:

- What changed and why.
- What became simpler or faster, with before/after evidence when available.
- Verification performed and its duration.
- Remaining concrete risks or blockers (not speculative possibilities).

## Final self-check

Before finishing, ask:

- Did I build only what was requested?
- Can I remove a layer, file, dependency, option, branch, or test without harming a current requirement?
- Is each test tied to realistic behavior?
- Did I measure the problem instead of guessing?
- Would a senior engineer maintaining a four-person MVP call this direct and proportionate?

If any answer reveals unnecessary work, simplify before stopping.
