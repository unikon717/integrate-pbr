# 训练数据格式与审核流程

Historical v3 scratch experiments are recovery-only and unsupported by current evaluation or warm-start. Current CLI, data contracts, native-pixel fidelity and false eligibility requirements below govern new work.

## 离线检查 scratch 模型

使用 `python -m integratepbr_engine diagnose --dataset-root ROOT --manifest VALIDATION_JSONL --weights MODEL.safetensors --labels contracts/labels.json --output NEW_DIR --cpu` 生成 `diagnostic-report.json` 与五个通道的联系表。输出目录必须尚不存在。默认依次选 Birch Planks、Stone Bricks、Birch Log Top、Stripped Birch Log Top、Birch Door Top、Birch Door Bottom、Iron Block 七张验证贴图。门的两张方块贴图分别作为原生输入和指标行；手持物品图 `assets/minecraft/textures/item/birch_door.png` 从默认诊断中排除。另生成原图上半部叠下半部、最近邻放大的 `birch-door-placed-preview.png`，以及只记录用户高层指导、不提供像素或数值训练真值的 `annotation-note.json`。运行前核验权重、清单、标签及所选源图和目标图的原始字节哈希。报告列出训练时和当前代码哈希；新增 CLI 会使 `__main__.py` 与训练快照不一致，dataset.py 的当前差异如实记录，network.py 必须一致，preprocess.py 的历史哈希为空。

每张联系表按原图、loader 清理后的参考、网络原始预测、误差四列排列。源像素只在展示时以最近邻放大到固定单元格。连续通道统一用 0..1 灰度，不逐图拉伸；品红色表示透明或没有标签的像素。金属类型使用固定类别颜色，误差列只表示正确或错误。数值统计仍在原生分辨率完成，按有效不透明标签像素计算；主体深度另报告乘以 255 的 LabPBR alpha 步数。零支持指标为 `null`，汇总误差按支持像素数加权。

这些图和数字只诊断同源、未经人工审核的参考通道与网络原始输出。对象类型、结构、边界和细节深度缺少有效标签，均不评估；材质监督只有金属阳性证据，不能解释为一般语义或材质准确率。历史 loader 将归一化 alpha 再除以 255；hash-pinned diagnose 明确使用 rgba5-legacy-alpha-v1 复现该变换，并非完整历史代码重放。当前训练/评估使用 rgba5-v2，RGBA 只除以 255 一次，valid 为 alpha > 0。该离线结果无法证明花纹、接缝、年轮、高度规则、最终约束图或游戏画面质量，也不能作为可部署结论。

训练集由审核过的原贴图与目标图构成。未审核的生成结果只能用于候选标注，不能直接当作真值。数据放在仓库外；路径必须相对 `--dataset-root`，训练、验证和测试按模组、原画及派生关系分组。

```text
dataset-root/
  textures/mod_a/planks.png
  targets/mod_a/planks.npz
  train.jsonl
  validation.jsonl
  test.jsonl
```

每行 JSONL 描述一张贴图。类编号使用 `contracts/labels.json` 对应数组中的索引；数组顺序才是训练时的数值 ID。

```json
{"sample_id":"mod_a:planks_oak","source_artwork_id":"mod_a:planks_oak:v1","derivative_group":"mod_a:oak_planks","mod_id":"mod_a","material_family":"wood_planks","style_family":"pixel_16","source":"textures/mod_a/planks.png","targets":"targets/mod_a/planks.npz","name":"Oak Planks","object_type":9,"object_materials":[0,1,0,0,0,0,0,0,0,0,0,0,0,0],"metadata":[0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],"reviewed":true,"reviewer":"human","license":"documented source permission","annotation_version":1}
```

`object_materials` 按材料词表顺序给出多标签；`null` 表示未知、不参与损失。整项省略时全部按未知处理。`metadata` 必须为 64 个有限的 `[0,1]` 数值，顺序见 [`metadata-features.json`](../contracts/metadata-features.json)。对照样本记录来源和许可；“不把贴图打进模组”不替代来源审查。

## NPZ 目标数组

目标文件只保存下列同尺寸二维数组，必须与源 PNG 的宽高一致，使用 `float32`。分类图以 `255` 标记未标注像素；连续图以 `NaN` 标记未标注像素。

| 数组 | 值域 / 约定 |
| --- | --- |
| `material` | `labels.json` 的 `materials` 索引；255 表示未标注 |
| `structure` | `structures` 索引；255 表示未标注 |
| `boundary_x`, `boundary_y` | 0/1；NaN 表示未标注。只描真实区域边界，保持统一标注线宽 |
| `base_depth`, `fine_depth` | 归一化 `[0,1]` 下陷深度，映射到 LabPBR alpha 的策略由编译器配置负责 |
| `smoothness` | 归一化感知光滑度，勿与线性粗糙度混淆 |
| `dielectric_f0` | 归一化非金属 F0；金属像素由 `metal_type` 表示 |
| `metal_type` | `metals` 索引；255 表示未标注，非金属为 0 (`none`) |
| `ao` | 归一化 AO；没有独立 AO 参考时，不从光照阴影伪造 |

当前 loader 要求上述目标齐全，但连续目标允许局部 NaN。参考必须与源 PNG 的像素空间、透明边缘、动画帧一致；重画布局或年轮的颜色图不能当配对监督。模型先输出浮点数，再经区域约束和 LabPBR 编码。

`prepare-reference` 仅从同路径的颜色、`_n`、`_s` 三图提取可直接观察的通道：`_n` A 为主体深度、B 为 AO，`_s` R 为光滑度、非金属 G 为 F0，G 的金属编码映射为 `metal_type`。透明像素不参与监督。金属编码像素可标局部 `metal` 材质及对象级金属存在（1）；其它对象材质保持 `null`，非金属局部材质保持 255。细节深度、结构及边界没有直接证据，分别保留 NaN、255、NaN。文件名和路径推测仅存于 `candidate_*` 字段，`material_family` 和 `derivative_group` 只用于切分。参考行使用 `supervision_source=exact_reference_pbr_pair`、`reviewed=false`，并记录压缩包名称、SHA-256 及归档条目。它们是有限的参考通道监督，不能作为语义或结构已审核的证据。

Loader 对旧版未审核参考行也执行相同的监督边界：清除对象类型、非金属对象材质、非金属局部材质、结构、边界及细节深度；金属阳性只由有效像素的 `metal_type>0` 重建。其它未审核来源被拒绝。人工核对源图、像素对应、标签及来源条件后，才能将目标图与行记录改为 `reviewed=true` 并填入审核人和版本；审核后的稀疏标签按记录原样使用。评估 JSON 按任务记录实际标签支持量，零支持指标为 `null`，并列出来源及审核状态数量。仅含参考样本的指标不代表跨模组或视觉质量。

## 人工审核包

使用 `review-packet --dataset-root ROOT --manifest VALIDATION_JSONL --training-root DATASETS_PARENT --output NEW_DIR` 生成新的审核目录，默认选 16 张。命令审计 `DATASETS_PARENT/*/train.jsonl` 的哈希与原画/派生组交集；交集样本只作诊断，不列入可导入草稿。`index.json` 和 `audit.json` 保存来源、碰撞、类别候选及覆盖缺口。`previews/` 是最近邻放大、带像素格线的源图与已有深度、光滑度、金属测量；`sources/`、`measured_targets/` 保留自包含原始审查材料。文件名类别只是选片候选，不能当作标签；细小配件必须逐像素查看。

审核者在 `drafts/<sample_id>.json` 中填写 `review_status=approved`、非空 `reviewer`、`review_date`、正整数 `annotation_version`，并在 `object_type` 或 `object_materials` 中填写有证据的语义。可在配套 NPZ 中局部标注材质、结构、边界及细节深度；未知处继续保留 255/NaN。`evidence` 与 `unresolved_questions` 记录判断依据和疑点。`import-review --packet PACKET_DIR --training-root DATASETS_PARENT --output NEW_DATASET_DIR` 复核源图与训练清单哈希、类别值、维度和新碰撞，仅将已批准样本与已有直接 PBR 通道合成一个新数据集。输出不得覆盖旧目录。已知清单无交集仍不代表模型训练谱系已验证，也不构成跨模组或盲测结论。

## 审核和切分

- 优先覆盖木板、砖及裂纹/苔藓/雕纹变体、普通与剥皮原木截面、门的混合材质、金属装备，以及暗斑、绘制高光、透明像素等反例。
- 材质、结构、边界、深度、光滑度、金属类型分别标注；不确定处留空，不靠名字填充像素真值。
- 同一模组、原画变体/换色及其派生必须落在同一切分。训练入口拒绝 `source_artwork_id` 或 `derivative_group` 泄漏。
- 测试集不能用于阈值或架构调参；按模组及材料族报告指标和跳过/不确定占比。
- 少量样本训出的权重只用于实验，不能随模组发布。先核验任务定义和数值尺度，再逐步扩充。

## 渲染表面用法契约

`contracts/surface-usage.v1.json` 是离线、版本化的定性用法契约。只有精确匹配样本 ID 与归档条目的用户确认记录，或带所有者、模型、状态、渲染器、资源引用的已核实渲染表面证据，才能确定 `item_surface` 或 `block_surface`。物品所有者可引用方块模型面；此时实际渲染面仍是方块面。独立证实两种表面时为 `conflict`，缺少证据时为 `unresolved`。路径、名称、候选对象类型和旧的 64 维元数据仅是提示。

桦木门物品图是手持图标，使用宽泛木材粗糙度和克制的起伏；放置的上下半门是详细 PBR 检视重点。用户确认上半部大片浅白内板为木材、左右深灰小块为金属配件。这些信息没有像素坐标、掩码、金属种类或数值粗糙度，也不是已审核训练标签。后续资源发现需要实际的 owner、model、state、renderer 与 UV 证据。未来共享编码器可以设置小型物品/方块输出头；本阶段没有创建这些头，也没有使实验检查点可部署。

## 当前预处理与模型包边界

新训练应使用新的空输出目录并保持审核与分组约束，本次未运行训练。最终 model-metadata.json 记录包版本、context_swin_unet_v2、rgba5-v2、labels.json 原始字节 SHA-256、权重 SHA-256、参数数及 run-manifest 链接。evaluate / train --init-weights 在加载前验证身份、本地路径与参数数，再严格加载；裸权重、旧 scratch 包、缺少预处理身份及中断训练的未盖章产物不兼容。纠正 alpha 不能证明视觉质量提升，仍需独立跨模组评估及用户验收。

generation-job.v1.schema.json and generation-result.v1.schema.json define the earlier foundation transport-schema boundary. The experimental static offline generate path is now described below; no dispatcher, Java integration or model-quality acceptance exists. context.attributes and policy.overrides are deliberate extension objects; other fixed records reject extra fields. Schema path rules alone do not verify filesystem existence/containment or cross-document ID equality; the supported offline profile performs its explicit runtime checks.


## Experimental static offline generation

The shared engine now exposes `python -m integratepbr_engine generate --job JOB_JSON --job-root ROOT --weights LOCAL_MODEL.safetensors --labels LOCAL_LABELS.json`. The supported policy is `offline-generic-experimental`, version `1`, for explicitly declared static item/block bounded planes in X-right/Y-down orientation. Optional 64 metadata features retain their established order; absent context defaults to incomplete. Evidence is preserved, not interpreted as reviewed labels. Animation metadata, unsupported UV topology/orientation and transparent sources are skipped.

Compatible local packages require current preprocessing, identity hashes, actual parameter count, package ID and version provenance. The historical trained checkpoint remains incompatible and is never relabeled. No accepted compatible trained weights exist. Tests use a seeded package labeled `random-test-fixture` only to establish CPU execution.

Outputs preserve original PNG bytes and decoded RGBA, including hidden RGB. Actual native predictions are retained in NPZ. Conservative constraints floor clipped base depth to at most two height alpha units (optionally tighter); fine depth is saved but unapplied. Metal gates are uncalibrated. DirectX normals derive from final stored height with bounded neighbors and explicit quarter-UV scale. Transparent companions are neutral. Artifacts, provenance, hashes and result are staged and published together; successful experimental jobs report `partial`, never accepted completion.

This path does not implement regional hierarchy/policies, animation, UV transforms, Java routing or distribution. Numeric/format checks and repeatable random inference establish no perceptual quality, held-out cross-mod acceptance or in-game validation. No training or game launch is part of generation validation.


## Development resource snapshots and finite queue

`/integratepbr held snapshot` and `/integratepbr block snapshot` explicitly capture the selected registry owner into a fresh `integratepbr-dev/snapshots` development directory outside resourcepacks. Capture is bounded and synchronous; it performs no inference/reload. JSON references remain candidates. Renderer, rendered surface, UV topology/orientation and tint stay unknown. Shared discovery is only the bounded registered-JSON scope; omissions invalidate its completeness. Exact generated pack ID `file/IntegratePBR_Generated` is excluded from low-to-high source stacks; independent PNG, sidecar and companion providers/hashes are retained.

Snapshot identity hashes canonical semantic content without the ID: null N, boolean T/F, integer I<decimal>;, UTF-8 string S<byte-length>:<bytes>, array A<count>:<elements>, object O<count>:<sorted key/value elements>. No timestamp or destination enters identity. Export stages exact bytes and publishes manifest last; snapshot and prepared outputs are immutable new directories. Bounds are 4096 owners, 8192 JSON reads, 256 KiB per/8 MiB total JSON, 128 selected textures, 4 MiB per/16 MiB total assets, and PNG dimensions at most4096 with at most16777216 pixels.

`python -m integratepbr_engine prepare-snapshot --snapshot-root ROOT --output-root NEW_ROOT` validates identity/bytes and exports coverage with no jobs by default. Optional `--package-metadata FILE --declarations FILE --experimental-offline-plane` creates a finite laboratory queue only when explicit declarations bind snapshot ID, full texture resource ID and source SHA256. Scope is `offline_image_plane_not_verified_game_uv`; surface must match sole observed registry kind. Mixed owners, incomplete discovery, armor-only candidates, animations, absent/transparent source and existing external PBR remain ineligible. Package metadata alone does not verify weights or accepted model quality.

Consume a prepared job explicitly with `python -m integratepbr_engine generate --job NEW_ROOT/jobs/JOB_ID.json --job-root NEW_ROOT --weights LOCAL_MODEL.safetensors --labels contracts/labels.json`. Preparation never starts inference automatically. The queue contains relative paths, not executable shell strings. Offline Java-export→Python-prepare→random CPU-generation fixtures demonstrate transport mechanics and source fidelity only. No live-game capture validation, worker daemon, result import, active-pack publication, training or deployment occurs.


## Source-backed snapshot v2 geometry evidence

New snapshots use v2 and preserve exact bounded model/blockstate source JSON bytes/providers/hashes separately from PNG assets. V1 remains supported with geometry evidence unavailable. Preparation reports a single pure offline JSON resolver's contextual model uses, inherited elements, actual face texture aliases, six vanilla default UV formulas, explicit/reversed UV and rotations, declared tint, item override predicates and blockstate conditions. Raw JSON, including whitespace/order, participates in snapshot identity; derived floating geometry stays in the report.

Every use remains runtime_verified=false. Generated layers retain consecutive layer bindings without inventing alpha-side geometry; builtin entity/custom loader/visibility/transforms are unsupported, while missing/invalid/cyclic/budget-truncated dependencies are incomplete and block affected laboratory jobs. Full source geometry does not authorize automatic jobs or prove effective game UV/renderer/tint. Existing explicit offline-image-plane declarations and all prior companion/animation/shared-use/package gates remain required. This stage does not bake transformed quads, change normals/material policies, train, start a game, install dependencies or publish an active pack.


Explicit selected baked query snapshots
--------------------------------------
The held/block `runtime-snapshot` command exports v3 with a hashed bounded `observations/runtime.json` sidecar. Source-only snapshot remains v2. Client capture labels `client_runtime_query`; injected offline regressions label `test_fixture`. Python preparation reports these as live/synthetic baked-model query evidence, independently of discovered PNGs, including unmatched sprites and zero-source snapshots. This is selected API sampling without drawing: rendered_frame_verified=false, visible_faces_evaluated=false, source_mapping=unknown. No source attribution, existing chunk mesh reproduction, replay identity, runtime eligibility promotion, automatic job, or rendered-frame proof follows. Transient ModelData is opaque. Custom/trident and non-MODEL dispatch are unsupported; failed/truncated queries are incomplete.

Bounds include models32, passes8, types16 per pass, queries896, sprites256, quads2048 and128 per query, packed words64 (only32 decoded), observation4MiB, stack encoding64KiB, depth32 and100000 nodes. Quad tint and packed vertex colors remain separate; float32 positions/atlas UV and double local sprite UV retain mirrored/non-square/shrunken corners. Counts cannot preempt a mod callback that never returns. Registry-aware stack encoding does not certify replayability. V3 attachment corruption fails preparation; valid incomplete/unsupported observations leave independent laboratory source-image eligibility unchanged. Offline Java synthetic fixtures/API compilation do not establish live world, visibility, visual quality or game validation.


Blocks-atlas correspondence (v4)
-------------------------------
Explicit runtime-snapshot adds a hashed atlas-attribution sidecar and byte-exact recipe/PNG/metadata evidence. Source-only v2 and direct runtime-v3 remain compatible. Java replays only the current blocks recipe: direct single/directory, ordered filters with Java find semantics, and exact unsupported outputs from unstitch/palette; custom/malformed/bounded gaps remain unknown. Actual winners include the generated pack; excluded generated winners cannot be replaced by lower external diagnostics for pixel promotion.

Python independently compares bounded static original RGBA pixels (including hidden RGB at alpha0) to captured PNG bytes. Strongest status current_recipe_pixel_match means captured current recipe/pixel correspondence. It keeps load_time_provenance_verified=false, rendered_frame_verified=false and eligible_for_generation=false; no historical supplier provenance, renderer frame, cache eligibility, automatic jobs or quality claim. ResourceMetadata.EMPTY identity is required for the current sprite. Historical blocks_current_recipe_v1 candidates require an empty source metadata fact; new blocks_current_recipe_v2 candidates accept empty or unknown source metadata while retaining that fact. Both require no visible metadata sidecar/APNG and matching full dimensions. Unknown atlases, transforms, stale tokens, metadata and budget failures retain useful top-level records even without source PNG discoveries. Synthetic test_fixture origins remain distinct from untrusted client origin labels.

Caps:64definition layers/256KiB each/4MiB total,2048sources,4096directory entries per call/8192total,8192lookups/opens,1024resources/32MiB copied evidence,PNG4MiB/metadata256KiB,2048dimensions/4194304pixels and total sampled pixels,1024trace entries per mapping/16384total,8MiB sidecar/depth32/200000nodes. Limits cannot preempt a nonreturning callback or regex. No live game validation, native/GPU access, loader hooks or training is part of offline API/fixture acceptance.


Bounded public metadata limitation
---------------------------------
The production Resource wrapper never calls lazy Resource.metadata(): that supplier may open uncapped streams internally, so effective resource metadata is reported unknown. Absence of a visible .mcmeta is an exclusion fact, not EMPTY identity proof. The v2 public client path may yield current_recipe_pixel_match from bounded exact current source PNG/current static sprite pixels with raw source metadata still unknown. Derived source_metadata_verified=false and source_processing_equivalence_verified=false apply to both revisions and every outcome: source metadata and reload processing equivalence remain unverified. Historical v1 unknown records remain unsupported. Public three-argument Resource and actual resource-manager/filter offline regressions use a synthetic test_fixture sampler and verify zero source metadata supplier calls and hidden stream opens; they do not query a live game atlas. Synthetic fixture Access may provide explicit empty/present/unknown facts. SpriteContents.metadata is still checked through its safe field accessor, visible sidecars use counted capped streams with their actual separate provider, and final registered-object identity is checked after every resource/pixel callback. Completed resource/access reads are cached; cache hits consume no further opens/bytes.
