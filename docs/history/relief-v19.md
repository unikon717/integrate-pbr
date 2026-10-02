# Relief revision 19 — noise filtering

> Historical experiment record. Local paths and validation results describe that revision only.

Connected components previously allowed short dark speckles to borrow confidence from an adjoining seam. Directional support is now required at each pixel before component filtering. The bounded search also crosses tile boundaries. Only observed corners joining supported segments are recovered; no new seams are drawn.

Runs shorter than four source pixels at 16x16 are rejected unless supported corner recovery applies. Short accepted runs receive reduced height; long runs retain full height. Source colors remain unchanged. This is still a heuristic: a long painted mark can resemble a joint, and a real very short isolated crack can be rejected.

Offline build and regression checks passed. Added checks cover isolated three-pixel marks, one/two-pixel spurs attached to a main seam, rotation, and real short joints between brick courses. Existing artwork, square-ring, normal direction, and animation-frame tests pass.

Twilight Forest sample recessed-pixel coverage (v18 → v19): planks_twilight_oak_0 32.8% → 29.7%; castle_brick 18.8% → 18.0%; canopy_log_top 32.4% → 23.4%. These are mask measurements, not a visual quality score.

Built in D:/MinecraftMods/pbr-qa/project-build because the running game locks the ordinary build artifacts. Updated D:/MinecraftMods/integrate-pbr-run/mods/integratepbr-0.1.0.jar and verified its hash. Prior JAR backed up outside mods in pbr-qa/backups/before-v19. The running development client is not hot-updated: next normal runClient launch compiles the updated source and cache version 19 regenerates maps. No game process was started or stopped. In-game quality remains to be checked by the user.
