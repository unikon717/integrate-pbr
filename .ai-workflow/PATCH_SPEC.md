# PATCH_SPEC
Status: INACTIVE
Tech Lead: GPT-6.1 Sol / high, 2026-10-03

All isolation recovery patches superseded by accepted isolation-complete-78c2b1. Source/docs/artifact checks and scoped cleanup complete; no unresolved implementation condition. Primary SPEC and PLAN COMPLETE for local implementation; Root owns publication only to feature/model-pbr, preserving canonical main.

No historical patch replay. New work requires current Architect PLAN and Lead SPEC; first substantive mutation/build/test/validation failure returns Lead. Keep active workflows concise and overwrite current evidence rather than append histories.

Publication whitespace decision: inherited EOF blanks in contracts/labels.json, engine/configs/training.yaml and engine/pyproject.toml are byte-equal to verified local-before and remain unchanged. SPEC own extra EOF blank removed. Root restages SPEC, runs normal staged diff --check excluding only those three paths, then git -c core.whitespace=-blank-at-eof diff --cached --check on exactly those three. Require both exit0; runtime override only, no Git settings or preserved-source edits. No tests rerun; local implementation acceptance unchanged.
