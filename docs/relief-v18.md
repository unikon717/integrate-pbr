# Relief revision 18 — 2026-09-29

## Implemented
- Correct depth-to-normal sign; normalize block normals and account for texel size. Item frame boundaries no longer sample adjacent frames.
- Replace whole-row/column extrusion with local dark-ridge evidence, connected-contour filtering and observed corner recovery. Detection is rotation symmetric and cannot fill a bright gap or extend a finite seam.
- Upsample source colors exactly (nearest neighbor). Distance inside the detected contour creates narrow bevels and flat faces; no procedural rings, replacement plank layouts, fabricated cross-joints or baked darkening.
- Separate wood face (148), end grain (126), bark (87), and masonry (123) smoothness; recesses are rougher. These baselines are informed by the supplied reference maps, not a claim of visual equivalence.
- Accept plural bricks/tiles in the material classifier. Cache version 18 regenerates affected output on next normal generation.

## Validation
`build` passes, including dependency-free `surfaceRegression` via `check`. Assertions cover original colors, rotation, finite seams, square contour corners, periodic seams, normal/height direction, transparent-block fallback, plural classification, and item animation frame isolation.

Offline Twilight Forest samples: wood/planks_twilight_oak_0, canopy_log_top, castle_brick. All have height alpha 207–255 and zero normal/height slope-sign disagreements. Recess coverage: 32.8%, 32.4%, 18.8% respectively. Horizontal and rotated vertical synthetic seams each preserve 16 source pixels; a half seam extends into zero unmarked source pixels.

Build artifact: D:/MinecraftMods/pbr-qa/project-build/libs/integratepbr-0.1.0.jar.
No game launch, game shutdown, runtime-pack replacement, shader/mod update, or GitHub upload was performed.

## Limits and next visual check
This remains a local image heuristic, not semantic understanding. Colored decoration can resemble a seam; low-contrast or wide seams can be missed. The algorithm cannot reproduce reference cross-joints absent from the source artwork. The reference is a quality target, not geometry to copy.

Metal region classification and artist-like metal facet construction have not been redesigned in this revision; existing item processing receives the depth sign/frame correction. Do not represent this revision as solving all metal-material quality issues.

The user must compare generated wood, log end/bark, and masonry against the reference in the same scene. Check narrow sharp bevels versus puffed faces, seam continuity, and source motif preservation. Offline checks do not establish final in-game quality. User controls game lifecycle. GitHub work remains paused.
