# Integrate PBR

Integrate PBR 是面向 **Minecraft Java 版 1.21.1 / NeoForge** 的客户端模组。它为已安装内容模组的方块和物品生成一个可选择启用的 **labPBR 资源包**，让支持 labPBR 的光影能够读取法线、高度和材质反射信息。

很多内容模组提供了精美的颜色贴图，却没有配套的 PBR 贴图。Integrate PBR 会查找这些模组实际使用的贴图，生成缺少的 `_n.png` 和 `_s.png`，并将结果放进**同一个资源包**。玩家可以在游戏的资源包界面决定是否使用它。

## 它会做什么

- 从已注册的方块和物品出发，沿常规模型引用寻找模组贴图；不处理原版贴图，也不覆盖其他资源包已有的 PBR 图。
- 根据名称、同一模组中的材质家族和贴图本身，推断木材、石材、金属等材质。混合贴图中的部分区域可以分别使用木质和金属参数。
- 只沿原图已有的清楚纹路制作起伏。对适合增强的低分辨率方块，颜色图仅做最近邻放大，保留原有颜色、图案、板缝、砖缝和年轮。
- 缓存生成结果。贴图、模组和手动选择没有变化时，下次启动会复用已有文件。
- 把不确定的分类列入待复核清单，允许玩家禁用某个物品或方块的自动生成，或手动指定材质类型。

这个过程在本地完成，不需要内置视觉模型，也不需要联网分析贴图。生成质量取决于原图能提供多少可靠线索；遇到结构不明确的贴图，模组会采用保守的效果。

## 使用

需要 Minecraft **1.21.1**、对应的 **NeoForge**，以及支持 **labPBR** 的光影环境。把构建好的模组 JAR 放入游戏实例的 `mods` 文件夹。游戏启动后，在「选项 → 资源包」中启用 **Integrate PBR - generated labPBR maps**。生成的单一资源包位于该实例的 `resourcepacks/IntegratePBR_Generated`。

如需修正自动判断，手持物品或用准星指向方块后，在聊天栏使用：

```text
/integratepbr held status
/integratepbr held type metal
/integratepbr held disable
/integratepbr held auto
```

把 `held` 换成 `block` 可操作所指方块。`type` 可选 `generic`、`fabric`、`leather`、`metal`、`wood`、`stone`、`glass`、`plant`、`leaves`、`wood_metal`；`auto` 清除手动选择。输入 `/integratepbr review` 可以查看待复核的自动分类。选择保存在游戏实例的配置文件中。

## 当前范围

项目仍在迭代。常规 JSON 模型引用和约定路径下的盔甲贴图是目前的主要覆盖范围；特殊模型加载器、实体渲染贴图及部分程序绘制的贴图可能遗漏。自动分类也不能从颜色贴图准确还原真实材质。游戏内最终观感需要玩家自行判断和调整。

多个对象共用同一张贴图时，对其中一个对象禁用生成会同时影响使用该贴图的其他对象。资源包只在本机游戏实例中生成，不包含参考资源包的贴图。

## 从源码构建

安装 **JDK 21**，在项目目录运行 `./gradlew build`（Windows 使用 `gradlew.bat build`）。构建好的 JAR 在 `build/libs/`。开发客户端可用 `./gradlew runClient` 启动。Gradle Wrapper 已包含在仓库中，无须单独安装 Gradle。

参与开发、按模块定位代码或部署请看 [合作者指南](guidance.md)；主要改动见 [CHANGELOG.md](CHANGELOG.md)，早期实验记录保留在 [docs/history](docs/history)。

## Model branch layout

This branch preserves the inherited legacy generator at format22. Its packages are `client`, `config`, `pack`, and `texture`; the experimental model capture path is independent under `model/discovery` and `model/client`. Model capture does not run the legacy generator or approve generation.

Use `/integratepbr-model held snapshot`, `/integratepbr-model block snapshot`, or the corresponding `runtime-snapshot` command to export development inputs to `integratepbr-dev/snapshots/<UUID>`. Runtime and atlas evidence remain incomplete observations; all proof and generation eligibility flags stay false.

There is one Python package and CLI: `engine/src/integratepbr_engine`. `snapshot`, `runtime_observation`, `atlas_source`, and `usage` prepare evidence; `geometry` and `preprocess` prepare inputs; `network` and `pipeline` execute the model; `constraints` and `labpbr` compile outputs; `dataset`, `training`, `review`, `diagnostics`, and `model_package` support experiments and packages. Contracts and configuration live in `contracts` and `engine/configs`; no parallel engine is maintained.

Build with JDK21 using `./gradlew build`. Offline Java checks are `surfaceRegression` and `resourceSnapshotRegression`; export fresh fixtures with `-PsnapshotFixture=<temporary path>`. Set `INTEGRATEPBR_SNAPSHOT_FIXTURE`, `INTEGRATEPBR_RUNTIME_FIXTURE` (path plus `-runtime`), and `INTEGRATEPBR_ATLAS_FIXTURE` (path plus `-atlas`), then run `python -m unittest discover -s engine/tests -p 'test_*.py'` with `PYTHONPATH=engine/src`. Fixtures verify mechanics and native source fidelity; they do not establish visual quality. Game launches and visual acceptance remain user controlled.
