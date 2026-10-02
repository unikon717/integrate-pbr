# Project constraints

- Generated color textures may enhance the source artwork only. Preserve its silhouette, motif, seams, ring shape, brick layout, and palette. Never invent joints, concentric rings, courses, grain patterns, or other geometry absent from the source.
- If the source has no reliable structure, leave its color texture unchanged and use restrained or flat PBR maps. A weaker effect is preferable to a fabricated feature.
- Base material rules on evidence that can generalize across installed mods, not a single Twilight Forest texture or screenshot.
- Verify generated albedo against its source and distinguish offline map checks from in-game visual validation. The user judges final quality and controls when the game launches or closes.

# Code boundaries

- Keep the root package limited to the mod entry point. Put event/command integration in `client`, manual choices in `config`, resource discovery and generated-pack orchestration/storage in `pack`, and pure image/material algorithms in `texture`.
- `texture` must not import Minecraft, NeoForge, client, config, or pack code. Keep algorithm helpers package-private; tests live in the same package. Do not introduce a framework or a Gradle subproject just to add a rule.
- Keep generated-map/cache writes and ownership checks in `GeneratedPackStore`; generation decisions and reload coordination belong to `GeneratedPackManager`. Preserve atomic file replacement, sidecar cleanup, and cache fingerprint semantics during refactoring.
- Use `guidance.md` for the current code map and development workflow. `docs/history/` contains historical experiments, not current instructions.
- Run `gradlew.bat build` (or `./gradlew build`); `check` includes the main-based `surfaceRegression` suite. The `test` task alone does not run that suite.
