# PLAN — isolate model system on feature/model-pbr

Status: COMPLETE — local implementation accepted; Root owns feature publication
Architect: GPT-6.1 Sol / max, 2026-10-03. Approved handoff; latest user instruction supersedes merge-main.

## Branch and recovery
Keep main at canonical origin/main eeb428830e1fb4a42845b387c43d300645a97d52, collaborator packages/store and legacy format22. Create feature/model-pbr from that commit; single active checkout. Restore canonical legacy bytes on feature too; local23 experiments recovery-only. Root handles refs/index/publication to feature only, never remote main. Preserve ignored files.
Verified132-file source backup/39remote files/local history bundle: D:/MinecraftMods/_archive/integration-20261002. Fresh5-file workflow644403bytes+hash manifest: D:/MinecraftMods/_archive/integration-20261003-workflow.

## Independent model responsibilities
Five maintained Java files: model.discovery.ResourceSnapshot owns Kind(ITEM,BLOCK)/Owner; ModelResourceIndex extracts latest bounded snapshot-only index path, retaining aliases/parents/overrides/owners/documents/limits and removing legacy dual-mode scan/content-mod branches; RuntimeModelObservation/AtlasSourceAttribution preserve current semantics. Their3 regressions same discovery package. model.client.ModelCommands self-registers /integratepbr-model held|block snapshot|runtime-snapshot; preserve thread checks/destinations. Legacy MaterialCommands unchanged. Model code has no legacy pack/config/texture imports; only mod identity/platform/IO shared.
Keep Bundle/token/Query/Access/Sampler/capture internals package-private. RuntimeModelObservation exposes withHeldAtlasObservation(Minecraft,Captured) and withBlockAtlasObservation(Minecraft,BlockPos,Captured), returning final Captured and attaching runtime+atlas from ONE bundle. No broad public helper API.
Single Python engine/CLI: keep current few maintained modules, contracts/configs/tests; no parallel engine/empty modules, behavioral/label/feature/preprocessing/checkpoint/protocol/eligibility changes. Document responsibility groups.

## Cleanup and docs
After backup/replacement delete exact obsolete flat Java/test copies and duplicate historical relief notes. Keep canonicallegacy/newmodel/runtime/data/required docs. PLAN/SPEC/RESULT/PATCH concise current-only, no historical appends/transcripts; archive exists. AGENTS preserves source-art/baseline and roles max/high/low+first-failure handoff. README distinguishes inheritedlegacy and experimental model; guidance current layout/build/checks; training-data current contracts/rules, remove obsolete duplication. Baseline current-layout note only, no changed quality/native-pixel/source-art/download constraints.
Ignore generated env/build/cache/bytecode/egg-info/log/data/weights. Cleanup generated pycache/log ONLY explicit inventory with resolved paths inside checkout. Preserve run/world/game/.venv/Gradle/model/data/reference/archive directories.

## Acceptance
Lead exact path allowlist/extraction/wrappers/commands/removals/docs/ignores/workflow/commands. First failure records evidence and returns Lead. Java21 offline compile/testClasses/SurfaceRegression/fresh ResourceSnapshotRegression/build/JAR pass. Task main classes texture.SurfaceRegression and model.discovery.ResourceSnapshotRegression; stable task/fixture args. Fresh Java source/runtime/atlas exports pass focused/full Python nativefidelity/discovery/identity/supplierzero/pixelv2/v1 compatibility. All proof/eligibility flags unchanged false, no autojobs. RandomCPU only mechanics. Temp-bytecode compile/import/schema structural/diff/path/class inventory pass, existing Windows symlink skips retained.
Root validates maincanonical, no model imports legacy; publish only feature single purposeful commit parentcanonical, verify remote/localrefs/tree/status. No generated publication/duplicates. No game/system/dependency/new inference/train/deploy. Next separate short PLAN: native captured inputs+supportedcontext -> shared model -> offline semantic/segmentation inspection, no invented UV/render claims.
