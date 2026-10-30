# OK-WW macOS

**基于 [ok-oldking/ok-wuthering-waves（OK-WW）](https://github.com/ok-oldking/ok-wuthering-waves) 二次开发的非官方 macOS 派生版本。** 本项目为原生《鸣潮》提供声骸、培养材料刷取面板；不是上游作者或游戏官方发布的 macOS 产品。

配套框架为 [Junsheng-He-Life/ok-script](https://github.com/Junsheng-He-Life/ok-script)，基于 [ok-oldking/ok-script](https://github.com/ok-oldking/ok-script) 适配 macOS。两个项目保留原有 AGPL-3.0 许可及上游归属，见 [LICENSE.txt](LICENSE.txt) 和[上游说明](UPSTREAM.md)。

[English](README_en.md) · [完整安装与使用教程](docs/beta-user-guide.md) · [开发说明](docs/development.md) · [问题反馈](https://github.com/Junsheng-He-Life/ok-wuthering-waves/issues)

## 下载与开始

当前版本：**0.1.0-beta.1，可安装的源码内测包**。已完成独立依赖环境安装验证和离线回归；多机器实机验收仍未完成。

**[下载 v0.1.0-beta.1](https://github.com/Junsheng-He-Life/ok-wuthering-waves/releases/tag/v0.1.0-beta.1)**，选择附件 **`ok-ww-macos-beta-0.1.0-beta.1.zip`**。该附件包含两个配套项目、安装入口和固定版本依赖清单。GitHub 自动生成的 `Source code` 压缩包不包含完整配套环境。

1. 准备 Apple Silicon Mac、macOS 14 或更新版本、Python 3.13、Xcode Command Line Tools，以及原生《鸣潮》客户端。
2. 解压完整附件，双击包根目录的 **`安装与检查.command`**。首次安装需要联网下载依赖。
3. 双击 **`启动.command`**，在“首次设置”完成权限和本机资源记录设置。
4. 游戏使用简体中文、默认键位并保持前台。先读取关卡、检查当前队伍，再设置额度开始短轮次测试。

Python 和系统权限的具体安装步骤见[用户教程](docs/beta-user-guide.md)。本包不需要 Codex，也不是自带 Python、已签名或公证的 `.app` / `.dmg`。Windows 用户请使用[上游 OK-WW](https://github.com/ok-oldking/ok-wuthering-waves/releases)。

## 面板预览

任务、资源额度和实际队伍集中在开始页；运行记录、异常恢复和首次设置分别展示。以下为示例界面，不含真实账号数据。

![开始刷取面板](docs/images/desktop-main.png)

窄窗口自动改为单列，内容可滚动，底部开始、暂停和结束操作保持可见。

![窄窗口面板](docs/images/desktop-small.png)

## 这一版能做什么

- **按实际队伍检查。** 每次开始重新读取三人身份、等级、生命值和索拉等级；换人或调整槽位后重新检查，不沿用旧队伍。培养材料需求从当前三人的培养目标重新读取。
- **集中设置刷取任务。** 提供无音区声骸、Boss 声骸和培养材料入口，以及声骸只吸收模式。能否执行取决于当前识别、策略和内测范围。
- **按本轮额度执行。** 波片、领奖份数、结晶溶剂和储备波片分别限制。补给默认关闭，溶剂与储备默认 0；达到任一停止条件即结束，不提供无限续跑。
- **保留消费记录。** 新使用者显式建立独立账本；已有历史、账本异常或待核对消费不能借初始化清零。声骸领取中断可在证据充分时核对，避免重复记账或再次领取。
- **适配 macOS 窗口。** 使用 ScreenCaptureKit 和原生前台输入，区分 Retina 像素与鼠标坐标。运行中发现游戏窗口几何变化会停止新输入，并释放已按下的按键。

## 已验证范围与边界

| 项目 | 当前范围 |
| --- | --- |
| 安装条件 | Apple Silicon、macOS 14+、Python 3.13、Xcode Command Line Tools；系统下限来自依赖要求 |
| 游戏条件 | 原生客户端、简体中文、默认键位、游戏保持前台 |
| 优先内测组合 | 索拉 8 阶、玄幽东岳无音区、秧秧·玄翎／弗洛洛／穗穗；角色槽位可调整 |
| 队伍门槛 | 三人等级至少 80、生命值至少 85%，身份及索拉等级明确；尚未自动核对装备和技能练度 |
| 面板 | 最小 920 × 600 逻辑像素；已做多种窗口尺寸及 1×、1.5×、2×离屏布局验证 |
| 游戏画面 | 配置支持 16:9、16:10、43:18，最低采集 1280 × 720；其他实际组合仍需验证 |
| 公开测试 | [公开离线子集](docs/development.md)：应用 111 项、框架 49 项通过，可从配套源码复跑 |
| 软件验证 | 全新依赖环境中 **620 项回归通过**，macOS 后端与启动错误模块 **49 项通过**，Swift 类型检查通过 |

上述安装和回归验证在同一台物理 Mac 上完成。**另一台 Mac、新账号、新面板完整实战链、真实暂停与中断恢复、多显示器现场切换，以及多套队伍连续刷取，仍待实机验收。** 离线测试通过不代表所有角色、关卡、显示器和系统版本都可稳定运行。

其他队伍或关卡需显式启用实验性组合，仍必须通过等级、生命值、身份、策略与消费保护。当前使用方式和排错步骤以[用户教程](docs/beta-user-guide.md)为准。

## 反馈与上游

遇到问题时先结束本轮，在“异常与恢复”导出诊断包，再提交 [Issue](https://github.com/Junsheng-He-Life/ok-wuthering-waves/issues)。附上版本、Mac 与系统信息、任务和队伍、复现步骤。诊断包不包含原始游戏截图、整份日志或账号配置；自行补充截图前请遮住 UID 和账号信息。

| 项目 | 归属 |
| --- | --- |
| 原版 OK-WW | [ok-oldking/ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) |
| 本 macOS 派生版本 | [Junsheng-He-Life/ok-wuthering-waves](https://github.com/Junsheng-He-Life/ok-wuthering-waves) |
| 原版 OK-Script 框架 | [ok-oldking/ok-script](https://github.com/ok-oldking/ok-script) |
| 配套 macOS 框架 | [Junsheng-He-Life/ok-script](https://github.com/Junsheng-He-Life/ok-script) |

感谢上游作者与贡献者提供的任务、识别和自动化基础。本项目保留原 [AGPL-3.0 许可证](LICENSE.txt)；分发、修改和提供服务时请遵守对应许可。维护和贡献请阅读[开发说明](docs/development.md)。

本项目通过屏幕识别与模拟输入运行。第三方自动化可能带来游戏账号风险，请自行了解并遵守游戏规则；软件按许可证规定以“原样”提供。
