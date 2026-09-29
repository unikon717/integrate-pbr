# Integrate PBR

面向 Minecraft Java 版 1.21.1 的 NeoForge 客户端模组。当前版本会从已注册的模组物品和方块出发，解析常规 JSON 模型实际引用的非原版贴图，为缺失的贴图生成 labPBR，并汇入一个可选资源包。对有可辨认原有结构的低分辨率、不透明木板、原木和砖块，会在该包中生成保持原图图案的轻度增强颜色贴图及对应的法线、高度；不会补画原图没有的板缝、砖缝和年轮。可在游戏中禁用目标或指定材质类型。

## 已确定的环境

- Minecraft 1.21.1
- NeoForge 版本见 gradle.properties
- JDK 21：C:\Program Files\Java\graalvm-jdk-21.0.12+7.1
- 项目位置：D:\MinecraftMods\integrate-pbr
- 测试光影：D:\MinecraftMods\sources\iterationRP Alpha 0.8.28.zip

已检查测试光影的压缩包。其 shaders/Lib/Settings.glsl 默认设置 TEXTURE_PBR_FORMAT=1；shaders/lang/zh_cn.lang 将数值 1 标为 labPBR。因此，第一版按 labPBR 规范生成与原纹理同名、以 _n 和 _s 结尾的贴图。

## 用 IntelliJ IDEA 打开

1. IDEA 已安装在 D:\IDEA\IntelliJ IDEA 2026.2.3。运行 D:\IDEA\IntelliJ IDEA 2026.2.3\bin\idea64.exe。
2. 启动 IDEA，选择 Open，打开 D:\MinecraftMods\integrate-pbr。
3. 如果提示信任项目，确认；等待 Gradle 导入。
4. 在 File > Project Structure > Project 中选择 JDK 21。
5. 在 Settings > Build, Execution, Deployment > Build Tools > Gradle 中，将 Gradle JVM 设为同一个 JDK 21，并将 Gradle user home 设为 D:\MinecraftMods\.gradle-cache。

IDEA 自身默认会把设置和缓存放在用户目录。若也希望它们留在 D 盘，参照 JetBrains 官方文档“Help > Edit Custom Properties”设置 idea.config.path、idea.system.path、idea.plugins.path 和 idea.log.path，各自指向 D 盘的不同目录。

## 在 PowerShell 验证

在项目目录打开 PowerShell，运行：

    $env:JAVA_HOME = 'C:\Program Files\Java\graalvm-jdk-21.0.12+7.1'
    $env:GRADLE_USER_HOME = 'D:\MinecraftMods\.gradle-cache'
    .\gradlew.bat build
    .\gradlew.bat runClient

首次运行需要下载 Gradle、NeoForge 和 Minecraft，时间可能较长。成功构建后，JAR 位于 build\libs。开发客户端启动后，日志中应出现“Integrate PBR detected mods:”。

## Git 与 GitHub

Git 已复制到 D:\MinecraftMods\tools\Git。IDEA 的 Git 可执行文件路径设为 D:\MinecraftMods\tools\Git\cmd\git.exe。

GitHub 上的空仓库地址是 https://github.com/unikon717/integrate-pbr.git。在 IDEA 的 Terminal 中，先只建立本地仓库并添加远程地址：

    & 'D:\MinecraftMods\tools\Git\cmd\git.exe' init -b main
    & 'D:\MinecraftMods\tools\Git\cmd\git.exe' config --global --add safe.directory D:/MinecraftMods/integrate-pbr
    & 'D:\MinecraftMods\tools\Git\cmd\git.exe' remote add origin https://github.com/unikon717/integrate-pbr.git

本地 Git 仓库已配置远程地址。提交与同步状态可在 IDEA 的 Git 面板查看。
## 使用生成的资源包

游戏启动后，会在该游戏实例的 `resourcepacks/IntegratePBR_Generated` 中维护**一个**资源包。打开“选项 → 资源包”，选择“Integrate PBR - generated labPBR maps”以启用。首次没有安装内容模组时，包可以是空的。

处理模组注册的物品和方块在常规 JSON 模型、方块状态文件中实际引用的非 `minecraft` 贴图，并为命名遵循常见 `textures/models/armor/<材质>_layer_1/2.png` 约定的盔甲查找穿戴贴图；已有来自其他资源的 `_n.png`、`_s.png` 不会重复生成。只有两张 PBR 图都需要本模组生成、且原图能提供可靠结构时，才会为合适的低分辨率方块同时生成保持图案的轻度增强颜色贴图，避免与其他资源包的 PBR 图错位。源贴图有 `.png.mcmeta` 时，生成图会带上同一份动画信息。文件内容和手动选择没有变化时，启动会复用现有结果。每次仍需读取源贴图以核对变化，但不会重新解码和写出未变化的图片。

## 手动材质选择

进入世界后，把目标物品拿在主手，或将准星对准目标方块，在聊天栏输入：

    /integratepbr held disable
    /integratepbr held type leather
    /integratepbr held auto
    /integratepbr held status

将 `held` 换成 `block` 可设置目标方块。类型包括 `generic`、`fabric`、`leather`、`metal`、`wood`、`stone`、`glass`、`plant`、`leaves`、`wood_metal`。`wood_metal` 会在同一张贴图内区分高置信度的金属与木质区域；其他材质选择仍以整张贴图为单位。`auto` 清除手动设置。选择写入游戏目录下 `config/integratepbr-overrides.properties`，重启后保留。修改后会在后台更新资源包，并触发资源重载；如果未启用生成的资源包，仍需先在资源包界面启用。

自动分类会结合物品/方块名称与模组实际贴图中的像素，也会从同一模组的注册名称学习材质家族：一个新词同时与锭/粒、矿石等名称共现时，可推断其金属制品；与树苗对应的名称可帮助识别木门、栅栏等；原石/圆石与加工形态成套出现时，可帮助识别石质构件。单独一个矿石名称不足以证明金属，矿石贴图本身也会标为可能混合石质和矿物。没有明确木/石材质线索的物品若同时具有耐久度和主手攻击力增益，也会暂按金属生成；这不依赖配方。陌生命名的装备若有明显的中性、冷色或金黄色刃部，也会暂按金属生成。所有这些推断都会列为待复核，不伪称已识别准确。在游戏聊天栏输入 `/integratepbr review` 或 `/integratepbr review 2` 可分页查看；完整清单位于游戏实例的 `resourcepacks/IntegratePBR_Generated/REVIEW.txt`。只修改过的贴图或其材质家族、武器属性线索发生变化时才会重新分类，待复核状态也随缓存保存。可使用 `held/block type` 或 `disable` 修正，清单会在更新后去掉手动指定的贴图。该清单覆盖的是常规模型扫描实际找到的贴图；非标准模型或程序绘制的贴图仍可能漏检。

当多个物品或方块共用同一张贴图时，一方的“禁用”会让该贴图整体停止生成，以确保被禁用的物品不再使用自动 PBR；其他共用者也会受到影响。相互冲突的手动材质类型同样会让该贴图停止自动生成。自定义模型加载器、程序生成的贴图和实体贴图暂未覆盖；常规模型引用的动画贴图会复制原贴图的动画元数据。

材质类型的初始参数参考了 D:\MinecraftMods\train-resource-pack 中布料、皮革、金属、木材、石材与树叶的通道分布；没有复制其中的贴图。通道编码遵循 [labPBR 材质规范](https://shaderlabs.org/wiki/LabPBR_Material_Standard)。

普通颜色纹理不能准确反推出真实金属度、粗糙度或高度。首轮游戏测试表明，直接把明暗转换为法线和高度会扭曲方块表面及手持物品的轮廓。当前金属物品用轮廓内侧和局部色彩变化生成法线；只有金属区域的内侧斜边和连续暗缝产生有限高度，透明区域保持平整。不确定的物品和方块保持平整。低分辨率、不透明的木板、树干和砖块只强化原图可辨认的暗缝与纹路，不添加新的板缝、砖缝或年轮；缺乏可靠结构时保留原图。`_s` 可按同一贴图内的木质和金属区域分别编码；金属物品的光滑度按可见像素相对明暗调整。参考包仅用于学习通道和材质区域的做法，没有复制其中贴图。视觉质量仍需在 iterationRP Alpha 0.8.28 中复测。

## 已验证

使用单独的最小内容模组测试：首次启动为其物品贴图生成 `_n`、`_s`；第二次启动复用缓存；设置 `disabled` 后移除两张生成图；改为 `fabric` 后重新生成并使用布料参数；在源模组提供 `_n` 后，仅保留本模组生成的 `_s`；资源包启用状态下启动与禁用目标也验证通过。`build` 和开发客户端启动均通过。测试模组与独立构建目录位于 D 盘，不在本仓库内。
首轮 iterationRP 实机检查发现，亮度推断的法线/高度会扭曲物品轮廓和方块表面。后续截图又发现，程序补画的木板接头、砖缝和圆形年轮改变了原图结构，宽缓高度使表面显得鼓胀。当前版本已撤除这些补画，只沿原图已有纹路生成起伏；金属物品保留内侧结构的有限高度，并扩大其光滑度变化范围。参考包锻造台的金属区域识别、暮色森林骑士/炽铁/铁木物品的通道检查及透明贴图检查通过。最近一次实机反馈显示，生成的木板、原木和砖块相对参考包仍过于平坦、边缘发钝。针对这个问题，当前代码增大了已有暗缝的高度与法线对比；原木端面只追踪原图中的连续暗纹，不补画年轮。三种暮色森林样本的离线检查及构建已通过，游戏内视觉质量仍待用户验证。

