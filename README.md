# OK-WW macOS 内测版

[English](README_en.md) · [安装与使用](docs/beta-user-guide.md) · [修复记录](docs/release-0.1.0-beta.3.md) · [问题反馈](https://github.com/Junsheng-He-Life/ok-wuthering-waves/issues)

**0.1.0-beta.3**：自带运行环境的 macOS App。所有培养角色共用刷取项目多选，默认仅声骸、不领奖；修复合鸣套装识别及生命上限变化时的回血核验。不需要 Codex，不自动上传日志。

![GUI](docs/images/desktop-main.png)

从 [Release](https://github.com/Junsheng-He-Life/ok-wuthering-waves/releases/tag/v0.1.0-beta.3) 下载 **OK-WW-macOS-arm64-0.1.0-beta.3.zip**。这是普通用户使用的独立 App；自动生成的 Source code 供开发者使用。

1. 使用 Apple Silicon Mac、macOS 14+。解压并将 **OK-WW 鸣潮助手.app** 拖到“应用程序”。无需另装 Python 或 Xcode。
2. 双击 App 打开 GUI；打开窗口不会启动游戏控制器。
3. 本版仅作本地签名，未经过 Apple 公证。首次被系统拦截时，核对来源与 SHA256 后在“系统设置 → 隐私与安全性”使用“仍要打开”。不要关闭系统整体保护。
4. 首次按教程检查屏幕录制、辅助功能权限；全新用户确认后建立本地账本。旧源码版用户先保留并核对原账本，不要将同一账号当作全新安装。
5. 游戏选好出战队伍，GUI读取队伍和关卡，**从下拉列表选择**。首次关闭领奖测试1场。

App 包含 Python、锁定依赖、OCR 模型和预编译原生组件，移动 App 不影响运行。个人数据位于 `~/Library/Application Support/OK-WW`，更新 App 保留数据和未核对消费。另提供配套源码 ZIP；源码安装仍需 Python 3.13 与命令行工具。Windows 请使用[上游版本](https://github.com/ok-oldking/ok-wuthering-waves/releases)。

| 任务 | 如何选择 |
| --- | --- |
| 无音区 / Boss | 读取列表，从下拉框选择副本 |
| 指定材料副本 | 选择副本和一名培养角色；战斗用当前队伍 |
| 按角色培养需求 | 选择当前三人、指定一人或三人，现场读取缺口 |
| 资源限制 | 场数/份数、波片、储备、溶剂；双倍领奖算2份，任一额度用完即停 |

默认**不领奖、不补给**。关闭领奖强制消费额度为0；自选培养支持不领奖练习。培养角色不会自动改变出战编队。

支持暂停/继续、立即停止、打完本场停止。暂停只停输入，不暂停游戏敌人。关闭面板会先停止控制器、释放按键并保留消费保护。

报错后在“记录与问题报告”选中失败运行，导出**脱敏诊断ZIP**，打开GitHub表单手动附上。包括版本、依赖、任务、错误栈、消费状态与脱敏日志尾部，默认不含截图、完整日志或账号配置。额外截图先遮住UID和账号名。不要删除保护文件解锁或重复领奖，详见[教程](docs/beta-user-guide.md)。

本版现场核对“心”的衔梦照世之心套装，并以玄翎／弗洛洛／穗穗完成沉心域、烬心域限额领奖。回血上限变化分支通过离线回归，最终通关未触发紧急治疗。1080p是主要实测画面；周本、部分Boss、地区同名入口、野外聚落和多机器仍有未验收范围，不表示所有角色/关卡稳定。

项目含AI辅助开发代码，请先零消费测试并保留反馈。上游关系和许可证见[UPSTREAM.md](UPSTREAM.md)，原始许可证随源码保留。
