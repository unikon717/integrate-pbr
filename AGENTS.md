# Project constraints

- Read `docs/model-architecture.md` before planning or changing the generation architecture. It is the user-approved architectural baseline for this branch; later explicit user instructions take precedence. It describes the target, not functionality already implemented.
- The target is a compact context-conditioned Swin U-Net hybrid for model-led object understanding, material/structure segmentation, and regional PBR prediction. Preserve native-pixel convolutional skip paths; do not drop one-pixel edges through coarse patchification. Do not substitute more per-name heuristics for this refactor or quietly route model failures through the old generator.
- Keep the default complete AI installation download near or below 1 GB (decimal), accounting for all required models, processors, and inference runtime. Report model bytes and runtime bytes separately. Prefer a shared compact multi-task network; a multi-billion-parameter vision-language model is not the default player dependency. Size allocations and network dimensions are experiment targets, not validated results.
- Preserve source artwork and apply the documented final-output constraints. Never claim perceptual quality is guaranteed by architecture, successful builds, model confidence, or file-format checks; require held-out cross-mod evaluation and user visual acceptance.
- Do not commit or push unless explicitly requested. Prefer maintainable changes to existing modules and a shared engine entry point over one-off scripts. Do not launch or close a game without applicable user authorization.

- Generated color textures may enhance the source artwork only. Preserve its silhouette, motif, seams, ring shape, brick layout, and palette. Never invent joints, concentric rings, courses, grain patterns, or other geometry absent from the source.
- If the source has no reliable structure, leave its color texture unchanged and use restrained or flat PBR maps. A weaker effect is preferable to a fabricated feature.
- Base material rules on evidence that can generalize across installed mods, not a single Twilight Forest texture or screenshot.
- Verify generated albedo against its source and distinguish offline map checks from in-game visual validation. The user judges final quality and controls when the game launches or closes.

## Multi-agent development workflow

- Keep maintained files concise. Replace active PLAN/SPEC/RESULT/PATCH with current decisions and evidence; archive superseded workflow history outside the checkout only when needed. Avoid repeated transcripts, duplicated guidance and one-off code; prefer shared maintained modules.

For future project implementation tasks, use the project-scoped Codex `architect`, `tech-lead`, and `executor` agents in sequence. Each stage must receive the prior stage's written output. A user request limited to inspection or configuration does not authorize implementation. Explicit user instructions and the constraints above remain in force.

1. **Architect — GPT-6.1 Sol / max:** Understand high-level requirements, analyze architecture and cross-module dependencies, and identify architecture-level risks and tradeoffs. Produce a written `PLAN`. Do not implement business code, perform mechanical edits, or patch local test failures.
2. **Tech Lead — GPT-6.1 Sol / high:** Convert the `PLAN` into `.ai-workflow/EXECUTION_SPEC.md` with `Status: READY`, allowed files, forbidden scope, interfaces, behavior, constraints, exact test commands, and acceptance criteria. Diagnose failures and write `.ai-workflow/PATCH_SPEC.md` with `Status: READY` when a patch is required. After execution, review the diff and test evidence before declaring completion. Tech Lead alone owns specification, diagnosis, and final review.
3. **Executor — GPT-6.1 Sol / low:** Read the active `EXECUTION_SPEC` or `PATCH_SPEC`, implement only the permitted changes, run specified checks, and write `.ai-workflow/EXECUTION_RESULT.md`. Do not redesign architecture, expand scope, change requirements or public APIs, add dependencies, or perform unrelated refactoring. If an unlisted file is absolutely necessary, stop and escalate to Tech Lead before modifying it.

### Test failure handoff

On a failed test or run, Executor stops blind edits and records the failing command, complete relevant traceback/error output, test output, changed-file list, and git diff summary in `.ai-workflow/EXECUTION_RESULT.md`. Tech Lead reads that result, the original `EXECUTION_SPEC`, the full git diff, and changed files, then classifies the cause as (a) implementation error, (b) `EXECUTION_SPEC` error or omission, (c) environment/dependency problem, or (d) architecture-level problem. Tech Lead produces a `PATCH_SPEC` containing the root cause, exact files and edits, forbidden changes, commands to rerun, and success criteria. Executor applies only that `PATCH_SPEC` and reruns the specified tests. Every further failure returns to Tech Lead; Executor must not enter an autonomous retry loop or assume Tech Lead duties.

If Tech Lead finds the original architecture or `PLAN` at fault, escalate to Architect for a revised `PLAN`, then issue a new `EXECUTION_SPEC` before Executor resumes. Successful path: Architect `PLAN` → Tech Lead `EXECUTION_SPEC` → Executor implementation and tests → Tech Lead final review → completion. `PATCH_SPEC.md` takes priority only while marked `Status: READY`; Tech Lead marks it `INACTIVE` after its review so a later execution uses the new `EXECUTION_SPEC`.

# Code boundaries

- Keep the root package limited to the mod entry point. Put event/command integration in `client`, manual choices in `config`, resource discovery and generated-pack orchestration/storage in `pack`, and pure image/material algorithms in `texture`.
- `texture` must not import Minecraft, NeoForge, client, config, or pack code. Keep algorithm helpers package-private; tests live in the same package. Do not introduce a framework or a Gradle subproject just to add a rule.
- Keep generated-map/cache writes and ownership checks in `GeneratedPackStore`; generation decisions and reload coordination belong to `GeneratedPackManager`. Preserve atomic file replacement, sidecar cleanup, and cache fingerprint semantics during refactoring.
- Use `guidance.md` for the current code map and development workflow. `docs/history/` contains historical experiments, not current instructions.
- Run `gradlew.bat build` (or `./gradlew build`); `check` includes the main-based `surfaceRegression` suite. The `test` task alone does not run that suite.

- model.discovery/model.client owns independent capture and never imports legacy pack/config/texture.
