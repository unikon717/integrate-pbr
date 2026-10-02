# EXECUTION_SPEC — isolate model work
Status: COMPLETE — local implementation accepted; Root owns feature publication
Tech Lead: GPT-6.1 Sol / high, 2026-10-03
Authority: approved PLAN; latest user instruction supersedes merge-main. Executor GPT-6.1 Sol / low.

Lead review 2026-10-03: accepted isolation-complete-78c2b1 and actual source/docs diffs. Current33 immutable canonical files byte-equal remote, feature/main/originmain pinned eeb; five independent model classes/three tests, unchanged engine/contracts. Java build/regressions and focused/full83 Python checks PASS (two existing Windows skips);17runtime/47atlas fixtures/source identity preserved, JAR175549bytes hashbbb5d71cfb37489370792bc0145a4fa6c04d366bd7ad21152e88bbc1bb021298. Docs UTF8/LF/diff PASS; obsolete27 and generated32/empty13 cleanup verified. Structural contracts/offline mechanics only; no live game/quality/eligibility proof. No unresolved implementation condition.

## Preconditions
One checkout D:/MinecraftMods/integrate-pbr. Root first establishes feature/model-pbr with HEAD/main at eeb428830e1fb4a42845b387c43d300645a97d52; Executor verifies branch/HEAD/main. No Executor ref/index/commit/network changes. Read AGENTS and architecture baseline. EVERY tools.apply_patch file target must be ABSOLUTE under D:/MinecraftMods/integrate-pbr; exec_command workdir does not change apply_patch cwd. Verify each intended target exists/content immediately after mutation before dependent work.

Immutable recovery: D:/MinecraftMods/_archive/integration-20261002, verified local-before/132-file manifest, remote-main/39-file remote-main.json, local-history.bundle. Former five workflows/644403 bytes are verified in D:/MinecraftMods/_archive/integration-20261003-workflow/manifest.json. Verify every copy/deletion against manifest; stop on mismatch/unbacked-up changes. Use ordinary apply_patch for protected source writes. First failed mutation/build/test/validation or unexplained substantive failure stops dependent work: replace RESULT with exact command/error, saved edits/checks/direct deltas and return to Lead. A known read-only search operand or quoting error may be corrected once locally without changing code/design; rg exit1 simply means no matches when absence is expected. If corrected inspection still fails or establishes a substantive blocker, hand off. No blind retries/permissions/system changes.

## Exact allowed paths
- Restore exactly the 39 paths in remote-main.json.files[].path from verified remote-main. Finite manifest, no glob. Canonical 17 production Java, SurfaceRegression, history/resources/templates/wrapper/properties/settings/license stay byte-identical. FORMAT_VERSION remains22. Only additive root edits listed below may differ from canonical.
- New production: src/main/java/dev/integratepbr/model/discovery/{ResourceSnapshot,ModelResourceIndex,RuntimeModelObservation,AtlasSourceAttribution}.java and model/client/ModelCommands.java (five).
- New tests: src/test/java/dev/integratepbr/model/discovery/{ResourceSnapshotRegression,RuntimeModelObservationRegression,AtlasSourceAttributionRegression}.java (three).
- Additive root edits: build.gradle, .gitignore, AGENTS.md, README.md, guidance.md, CHANGELOG.md. Existing local docs/model-architecture.md and docs/training-data.md. Executor replaces .ai-workflow/EXECUTION_RESULT.md with concise current evidence. PLAN/SPEC/PATCH owned by Architect/Lead.
- Delete only verified obsolete individual files after replacement: src/main/java/dev/integratepbr/{AtlasSourceAttribution,GeneratedPackManager,IntegratePbrClient,ItemStructure,LabPbrMaps,MaterialClassifier,MaterialCommands,MaterialLexicon,MaterialOverrides,MaterialRegions,MaterialType,ModelTextureIndex,ResourceSnapshot,RuntimeModelObservation,SurfaceEnhancer,SurfaceTone,TextureStructure,WeaponSignals}.java; src/test/java/dev/integratepbr/{SurfaceRegression,ResourceSnapshotRegression,RuntimeModelObservationRegression,AtlasSourceAttributionRegression}.java; docs/{relief-v18,relief-v19,relief-v20,relief-v22}.md; .ai-workflow/EXECUTION_SPEC.surface-usage.complete.md. Resolve each absolute path within repository before removal; no recursive deletes. Root IntegratePbr remains; canonical history is docs/history.
- Engine/contracts/configs/tests and .codex/agents/{architect,tech-lead,executor}.toml remain byte-identical to local-before. Read-only inspection allowed. Task-temp scripts/exports/bytecode and ordinary build/cache outputs only. Ignore rather than delete generated pycache/logs this stage. Preserve run/world/game/.venv/Gradle/model/data/reference/archive. No local23 legacy algorithms, extra modules/dependencies/protocol/labels/features/preprocessing/checkpoint/policy changes.

## Implementation
Move latest local-before ResourceSnapshot, RuntimeModelObservation, AtlasSourceAttribution and three regressions to model.discovery, preserving accepted pixel adapter v2 and v1 compatibility, native bytes, provenance, identities/ordering/limits, observations, zero supplier calls, all false proof/eligibility flags. Package/type changes must not change serialized data.

ResourceSnapshot owns public enum Kind { ITEM, BLOCK } and public record Owner(Kind kind, ResourceLocation id). Replace legacy Owner/Kind references in model code/tests. Keep required capture/export/Captured/attachment APIs; call ModelResourceIndex.snapshotScan.

Extract ModelResourceIndex from local dual-mode ModelTextureIndex into snapshot-only package-private class: retain bounded owner/model/blockstate/armor discovery, aliases/parents/overrides/builtins, depth/cycles, JSON/model caches, exact SourceDocument bytes/providers, omissions/evidence. Remove legacy ResourceManager constructor/read branch, scan/ScanResult/content-mod/registry/coverage/scannedOwners and recursive legacy alias path. Snapshot Access is always present, no null-access fallback. Retain processed/visiting semantics and signature static SnapshotDiscovery snapshotScan(Iterable<ResourceSnapshot.Owner>, ResourceSnapshot.Access, ResourceSnapshot.Limits). Helper records can be package-private. Model code has zero imports/references to legacy pack/config/texture algorithms.

Keep Bundle/token/Query/Access/Sampler/capture internals package-private. RuntimeModelObservation exposes only these added wrappers:
public static ResourceSnapshot.Captured withHeldAtlasObservation(Minecraft mc, ResourceSnapshot.Captured source)
public static ResourceSnapshot.Captured withBlockAtlasObservation(Minecraft mc, BlockPos pos, ResourceSnapshot.Captured source)
Each captures ONE existing bundle, attaches its bytes via withRuntimeObservation, then AtlasSourceAttribution.capture(mc, SAME bundle) via withAtlasAttribution. No public Bundle escape, second sampling or proof strengthening.

ModelCommands self-registers using client EventBusSubscriber/RegisterClientCommandsEvent, separate /integratepbr-model held|block snapshot|runtime-snapshot. Extract only snapshot behavior: player/world/held/block-hit guards, runtime main-thread check, selected owner first then deterministic registry owners, limits, UUID destination integratepbr-dev/snapshots/<UUID>, IOException/messages. Runtime commands call wrappers. No override/type/status/review/generation/reload branches. Canonical legacy MaterialCommands and IntegratePbrClient unchanged/import-free of model.

Tests update package/Owner/Kind/index references, retain existing assertions/goldens and add focused extraction/wrapper checks only as necessary. ResourceSnapshotRegression still invokes runtime/atlas regressions and exports source plus -runtime/-atlas siblings. Preserve test_fixture origin, 17 runtime/47 atlas fixtures and source snapshot ID d66027629c109be1ccb690c912f6cd55fa1cbae76ed72d8678d6bd06cd642260.

## Build/docs/ignores
Start build.gradle canonical; add supported neoForge.addModdingDependenciesTo(sourceSets.test), resourceSnapshotRegression JavaExec using dev.integratepbr.model.discovery.ResourceSnapshotRegression, test runtime classpath/testClasses dependency/optional snapshotFixture arg; add to check. Keep canonical texture.SurfaceRegression task and versions unchanged.

README/guidance: canonical legacy22 vs experimental model, responsibility paths/model commands/offline checks. CHANGELOG concise isolation entry. AGENTS preserve baseline/source-art/native-pixel/download/quality and max/high/low+first-failure roles. Architecture current-layout note only; preserve design. Training-data remove obsolete repetition but retain current CLI/contracts/native/proof limitations. Engine remains one maintained package; document groups, no empty shells. Ignore .venv, .gradle-user-home, build, __pycache__, *.py[cod], *.egg-info, logs and known generated data/weights; preserve canonical rules/wrapper exception and maintained source/config/contracts. No data movement or quality claims.

## Validation
Sequential, check external exit codes and stop first substantive validation failure under the handoff rule above. Process/task-specific variables only, no downloads/admin. Existing Java21 cached invocation:
```powershell
$isoJava = 'C:\Program Files\Java\graalvm-jdk-21.0.12+7.1\bin\java.exe'
$isoPy = (Resolve-Path '.\.venv\Scripts\python.exe').Path
$isoFixture = Join-Path $env:TEMP ('integratepbr-model-isolation-' + [guid]::NewGuid().ToString('N'))
$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP ('integratepbr-model-pycache-' + [guid]::NewGuid().ToString('N'))
$env:PYTHONPATH = (Resolve-Path '.\engine\src').Path
$env:PYTHONUTF8 = '1'
& $isoJava '-Dgradle.user.home=C:\Users\94787\.gradle' -classpath '.\gradle\wrapper\gradle-wrapper.jar' org.gradle.wrapper.GradleWrapperMain --offline --no-daemon --no-configuration-cache '-Porg.gradle.java.installations.paths=C:\Program Files\Java\graalvm-jdk-21.0.12+7.1' compileJava testClasses surfaceRegression resourceSnapshotRegression build "-PsnapshotFixture=$isoFixture"
if ($LASTEXITCODE -ne 0) { throw 'Java validation failed' }
$env:INTEGRATEPBR_SNAPSHOT_FIXTURE = $isoFixture
$env:INTEGRATEPBR_RUNTIME_FIXTURE = $isoFixture + '-runtime'
$env:INTEGRATEPBR_ATLAS_FIXTURE = $isoFixture + '-atlas'
foreach ($isoPattern in @('test_atlas_source.py','test_runtime_observation.py','test_snapshot.py','test_*.py')) {
  & $isoPy -m unittest discover -s .\engine\tests -p $isoPattern
  if ($LASTEXITCODE -ne 0) { throw "Python validation failed: $isoPattern" }
}
& $isoPy -m compileall -q .\engine\src
if ($LASTEXITCODE -ne 0) { throw 'Compileall failed' }
& $isoPy -c "import sys,importlib,pkgutil,integratepbr_engine; assert sys.pycache_prefix; [importlib.import_module(m.name) for m in pkgutil.iter_modules(integratepbr_engine.__path__, integratepbr_engine.__name__+'.') if not m.name.endswith('.__main__')]; print('imports/temp bytecode PASS')"
if ($LASTEXITCODE -ne 0) { throw 'Imports failed' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'Diff check failed' }
git status --short
if ($LASTEXITCODE -ne 0) { throw 'Status failed' }
```

Additional required read-only task-temp verification script: record exact script path/command in RESULT.
1. Canonical SHA256 against remote metadata for 17 Java, SurfaceRegression and immutable remote files; only six root additive files may differ. Legacy format22/no model imports. Direct model backup deltas (original untracked source is not covered by git diff).
2. SHA256 all maintained engine source/config/tests/pyproject, contracts and three agent configs against local-before. Parse every contract JSON structurally/equality with backup; not claim full instance validation.
3. Java inventory exactly17 canonical+five model production and canonical+three model tests, no obsolete flats. No model legacy package refs; wrapper one-bundle/private internals. Python zipfile inspect build/libs JAR: expected canonical/model classes, no flat duplicates/tests; record size/hash.
4. Fresh source identity and17runtime/47atlas counts/hash evidence; suites native fidelity/closed schema/supplier-zero/real manager fixtures/v1-v2 and unchanged false flags. Prior focused counts9 atlas,10runtime,13snapshot+1 existing WinError1314 skip; full81+2 existing skips (83total). Additional passes allowed; no new unexplained skips. Random CPU fixtures prove mechanics only.
5. Changed/deleted path allowlist and ignored generated output exclusion; ignored files remain. Record branch/HEAD/main, canonical/model direct diff summary, artifacts and limitations.

Executor concise RESULT replaces histories. Lead reviews actual diffs/evidence then COMPLETE/PATCH INACTIVE. Root alone publishes feature single commit parentcanonical and verifies remote main unchanged/ref/tree/status. No game/new inference/training/deploy; semantic model inspection needs next PLAN.
