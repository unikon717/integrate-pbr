# 合作者指南

这份文档说明怎样构建、测试和交付 Integrate PBR，以及哪些目录需要关心。项目面向 **Minecraft Java 版 1.21.1、NeoForge 和 JDK 21**。玩家功能与使用方式见 [README](README.md)，版本变化见 [CHANGELOG](CHANGELOG.md)。

## Quick Start

开始前只需要安装 **Git** 和 **JDK 21**。仓库已经包含 Gradle Wrapper，不需要单独安装 Gradle。以下命令会克隆源码、确认 Java 版本、编译模组并运行离线回归检查。

Windows PowerShell：

```powershell
git clone https://github.com/unikon717/integrate-pbr.git
Set-Location .\integrate-pbr
java -version
.\gradlew.bat build
Get-ChildItem .\build\libs\*.jar
```

Linux 或 macOS：

```bash
git clone https://github.com/unikon717/integrate-pbr.git
cd integrate-pbr
java -version
./gradlew build
ls -lh build/libs/*.jar
```

`java -version` 应显示 Java 21。首次构建需要联网下载 Minecraft、NeoForge 和 Gradle 依赖，之后 Gradle 会复用本机缓存。看到 `BUILD SUCCESSFUL` 和 `Surface regression checks passed` 后，JAR 位于 `build/libs/integratepbr-<版本号>.jar`，目前版本号是 `0.1.0`。

直接启动开发客户端：

```powershell
# Windows
.\gradlew.bat runClient
```

```bash
# Linux 或 macOS
./gradlew runClient
```

开发客户端的数据目录是仓库内的 `run/`。第一次启动会创建游戏设置、日志、资源包和存档目录。要在现有测试实例中运行，则先完全关闭该实例，再复制新 JAR。Windows PowerShell 示例：

```powershell
$instance = 'D:\path\to\your-minecraft-instance'
$mods = Join-Path $instance 'mods'
$jar = Get-ChildItem .\build\libs\integratepbr-*.jar | Sort-Object LastWriteTime -Descending | Select-Object -First 1
New-Item -ItemType Directory -Force -Path $mods | Out-Null
Copy-Item $jar.FullName $mods -Force
Get-FileHash (Join-Path $mods $jar.Name) -Algorithm SHA256
```

Linux 或 macOS 示例：

```bash
instance="$HOME/path/to/your-minecraft-instance"
mkdir -p "$instance/mods"
jar=$(find build/libs -maxdepth 1 -name 'integratepbr-*.jar' -type f | sort | tail -n 1)
cp -f "$jar" "$instance/mods/"
# Linux：
sha256sum "$instance/mods/$(basename "$jar")"
# macOS 没有 sha256sum 时：
shasum -a 256 "$instance/mods/$(basename "$jar")"
```

测试实例必须使用 **Minecraft 1.21.1 和 NeoForge 21.1.x**。若使用光影，还需要自行安装兼容该实例的 Iris、Sodium 和支持 labPBR 的光影；本项目不会自动下载或更新它们。进入游戏后，在资源包界面启用 **Integrate PBR - generated labPBR maps**。

使用 IntelliJ IDEA 时，直接打开克隆后的仓库根目录，选择 JDK 21，等待 Gradle 同步完成。右侧 Gradle 面板中的 `Tasks → build → build` 等同于上述构建命令；运行配置中的 `runClient` 等同于开发客户端命令。

日常验证使用同一个 `build` 命令，它会通过 `check` 自动执行 `surfaceRegression`。测试使用 main 入口，不是 JUnit；只运行 `test` 不会执行这套回归。修改生成算法后，还要由使用者在游戏内用固定场景比较原贴图与生成结果；离线检查不代表视觉质量达标。

### 常见启动问题

- `java` 无法识别：安装 JDK 21，并把其 `bin` 目录加入 `PATH`，或把 `JAVA_HOME` 指向 JDK 21 的安装目录后重新打开终端。
- `Unsupported class file` 或提示 Java 版本不符：再次运行 `java -version`，确认 Gradle 实际使用的是 Java 21。
- Linux/macOS 提示 `Permission denied`：运行 `chmod +x gradlew`，然后再次执行 `./gradlew build`。
- 修改后仍看到旧效果：确认测试实例中只有一个 Integrate PBR JAR；生成格式变化时还必须递增 `GeneratedPackManager.FORMAT_VERSION`，让旧缓存重新生成。
- 只想重新开始构建：运行 `./gradlew clean build`；Windows 使用 `.\gradlew.bat clean build`。`clean` 只清理仓库的构建输出，不会清理 `run/` 中的世界或游戏设置。

GitHub Actions 在推送和拉取请求时运行同样的 `./gradlew build`。目前它**只验证构建**，不会自动发布可下载的 JAR 或替换任何人的游戏实例。

## 目录怎么读

| 路径 | 用途 | 是否提交到 Git |
| --- | --- | --- |
| `src/main/java/dev/integratepbr/IntegratePbr.java` | 模组加载入口 | 是 |
| `src/main/java/dev/integratepbr/client/` | 客户端事件与玩家命令 | 是 |
| `src/main/java/dev/integratepbr/config/` | 手动材质选择的读取、保存与回滚 | 是 |
| `src/main/java/dev/integratepbr/texture/` | 材质分类、区域分析与贴图生成，不依赖 Minecraft | 是 |
| `src/main/java/dev/integratepbr/pack/` | 游戏资源发现、生成编排、缓存和文件存储 | 是 |
| `src/main/resources/`、`src/main/templates/` | 语言文件及 NeoForge 模组元数据模板 | 是 |
| `src/test/java/dev/integratepbr/texture/` | 不启动游戏的生成回归检查，与算法保持同包 | 是 |
| `gradle/wrapper/`、`gradlew*`、`build.gradle`、`gradle.properties`、`settings.gradle` | 构建配置和 Wrapper | 是 |
| `.github/workflows/` | GitHub 自动构建 | 是 |
| `docs/history/` | 历史实验记录，不作为当前开发指令 | 是 |
| `build/`、`.gradle/`、`.gradle-user-home/` | 本机输出与缓存；最后一个仅用于选择项目内 Gradle 缓存时 | 否 |
| `.idea/` | 本机 IntelliJ 设置 | 否 |
| `run/` | `runClient` 使用的开发游戏目录，可能有世界、设置、模组和日志 | 否；**不要当作普通缓存删除** |

### 按任务定位代码

| 想修改什么 | 先看哪个文件 |
| --- | --- |
| 事件注册、重载监听 | `client/IntegratePbrClient.java` |
| held/block/review 命令 | `client/MaterialCommands.java` |
| 手动选择的配置格式 | `config/MaterialOverrides.java` |
| 模型引用、贴图覆盖范围 | `pack/ModelTextureIndex.java` |
| 物品耐久度与攻击属性证据 | `pack/WeaponSignals.java` |
| 缓存指纹、生成顺序、重载时机 | `pack/GeneratedPackManager.java` |
| 输出路径、归属标记、PNG/mcmeta 与缓存写入 | `pack/GeneratedPackStore.java` |
| 整体材质与家族学习 | `texture/MaterialClassifier.java`、`MaterialLexicon.java` |
| 材质参数与局部分区 | `texture/MaterialType.java`、`MaterialRegions.java` |
| 方块结构、浅层高度与原图放大 | `texture/TextureStructure.java`、`SurfaceTone.java`、`SurfaceEnhancer.java` |
| 物品结构与 PBR 通道编码 | `texture/ItemStructure.java`、`LabPbrMaps.java` |

依赖方向：`client → pack/config/texture`，`pack → config/texture`，`config → texture.MaterialType`。`texture` 不反向引用游戏或文件存储模块；其包级算法辅助类保持内部可见，测试同包访问。材质和表面算法保留在一个纯算法包内，避免为了分目录扩大辅助 API。

资源重载或命令触发 `GeneratedPackManager`；它扫描引用、读取配置、检查缓存，然后调用分类与生成算法，最后经 `GeneratedPackStore` 保存。存储类负责文件操作，不决定材质、线程或重载。整理没有引入额外的 Gradle 子项目或规则框架。

## 本机调试与交付

启动和部署命令见 Quick Start。正式测试实例与 `run/` 分开，保留已有光影与世界，并确保 `mods/` 中只有一个本项目 JAR。当前构建仅配置客户端开发运行；未使用的 server、gameTestServer、data 和本地 Maven 发布配置已移除。

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

## Model branch layout

Independent capture code lives in `src/main/java/dev/integratepbr/model/discovery`; its commands live in `model/client`. The single Python package is `engine/src/integratepbr_engine`; shared schemas and configuration live in `contracts` and `engine/configs`. See [README Model branch layout](README.md#model-branch-layout) for commands and fresh fixture checks.
