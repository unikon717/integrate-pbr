# 合作者指南

这份文档说明怎样构建、测试和交付 Integrate PBR，以及哪些目录需要关心。项目面向 **Minecraft Java 版 1.21.1、NeoForge 和 JDK 21**。玩家功能与使用方式见 [README](README.md)，版本变化见 [CHANGELOG](CHANGELOG.md)。

## 从源码开始

1. 克隆仓库，并用 JDK 21 打开项目。IntelliJ IDEA 选择仓库根目录，等待 Gradle 导入完成。仓库自带 Gradle Wrapper，不需要另装 Gradle。
2. 在仓库根目录运行构建：Windows 用 `gradlew.bat build`，Linux/macOS 用 `./gradlew build`。构建同时运行离线的表面生成回归检查。
3. 成功后只取 `build/libs/integratepbr-<版本号>.jar`（目前是 `0.1.0`）。不要使用其他旧构建目录中同名的 JAR；需要确认时比较修改时间或 SHA-256。
4. 修改生成算法后，先运行构建与回归检查，再用游戏内的固定场景比较原贴图、生成结果和参考效果。离线检查通过不代表视觉质量已达标。

GitHub Actions 在推送和拉取请求时运行同样的 `./gradlew build`。目前它**只验证构建**，不会自动发布可下载的 JAR 或替换任何人的游戏实例。

## 目录怎么读

| 路径 | 用途 | 是否提交到 Git |
| --- | --- | --- |
| `src/main/java/dev/integratepbr/` | 模组代码：资源发现、分类、PBR 生成、缓存和命令 | 是 |
| `src/main/resources/`、`src/main/templates/` | 语言文件及 NeoForge 模组元数据模板 | 是 |
| `src/test/` | 不启动游戏的生成回归检查 | 是 |
| `gradle/wrapper/`、`gradlew*`、`build.gradle`、`gradle.properties`、`settings.gradle` | 构建配置和 Wrapper | 是 |
| `.github/workflows/` | GitHub 自动构建 | 是 |
| `docs/` | 较早实验的技术记录；玩家可读的变化以 `CHANGELOG.md` 为准 | 是 |
| `build/`、`.gradle/` | 本机生成的输出与项目缓存，可重新生成 | 否 |
| `.idea/` | 本机 IntelliJ 设置 | 否 |
| `run/` | `runClient` 使用的开发游戏目录，可能有世界、设置、模组和日志 | 否；**不要当作普通缓存删除** |

`IntegratePbr` 是模组加载入口，`IntegratePbrClient` 注册客户端行为。`ModelTextureIndex` 找贴图；`MaterialLexicon`、`MaterialClassifier` 和 `MaterialRegions` 判断材质；`TextureStructure`、`SurfaceEnhancer`、`SurfaceTone`、`LabPbrMaps` 生成图；`GeneratedPackManager` 组织缓存和单一资源包；`MaterialCommands` 处理玩家覆盖选择。改动前先看相邻类的输入输出，不要把所有规则塞回一个总类。

## 本机调试与交付

`gradlew.bat runClient`（Linux/macOS 用 `./gradlew runClient`）会启动开发客户端，默认数据目录是仓库内的 `run/`。正式测试实例应与它分开：把新构建的 JAR 复制到 **Minecraft 1.21.1 / NeoForge** 实例的 `mods/`，保留该实例现有的 Iris、Sodium、光影和世界。关闭游戏后再替换 JAR；不要把旧同名 JAR 一起放进 `mods/`。

首次启动后，在游戏的资源包界面启用 **Integrate PBR - generated labPBR maps**。生成结果存放在该实例的 `resourcepacks/IntegratePBR_Generated`。算法或输出格式变化时，应递增 `GeneratedPackManager.FORMAT_VERSION`，让旧缓存失效。检查生成覆盖范围可看该资源包中的 `COVERAGE.txt`；它列的是未发现非原版贴图引用的对象，不能直接等同于生成失败清单。

项目不附带任何参考资源包、光影或第三方模组文件。合作者需自行准备有权使用的测试资源；发布构建物时只发布本项目生成的模组 JAR。不要把游戏实例、世界、下载目录、参考贴图或生成的资源包提交进仓库。

准备公开版本时，先更新 `gradle.properties` 中的 `mod_version` 和 `CHANGELOG.md`，提交源码并确认 GitHub 构建通过，再用该提交构建 JAR。当前工作流没有发布步骤，因此 GitHub 上只有可构建的源码；如需向玩家提供二进制文件，维护者还需单独创建 Release 并附上经过验证的 JAR。

合作者应从 `main` 创建工作分支，按功能提交，并通过拉取请求说明改变了哪些材质行为、如何验证、哪些游戏画面仍需检查。修改影响玩家可见效果时更新 `CHANGELOG.md`。GitHub 构建通过后再合并；视觉质量仍须由实际游戏对比确认。

## 修改生成规则时

- 保留原图的轮廓、颜色、图案、板缝、砖缝与年轮。增强只可依据原图证据，不补画不存在的结构；线索不足时使用保守或平坦的 PBR 图。
- 用跨模组的材质家族、注册对象和贴图证据推断材质。混合材质要按区域处理，避免为了单个模组的截图写特例。
- 对高度图同时检查深浅范围、边缘是否清晰、透明像素与动画帧是否串色；法线方向必须与高度坡度一致。
- 为能脱离游戏验证的规则补充 `SurfaceRegression` 检查，再在游戏中看实际光影效果。最终质量由使用者判断；不要自行关闭正在运行的游戏。

维护者的本机工作区使用仓库旁的独立游戏实例、`pbr-qa/` 离线检查目录、共享 Gradle 缓存，以及单独保存的参考文件。它们**不是仓库的一部分**，也不是其他合作者必须复制的目录结构。
