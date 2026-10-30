# 上游来源与本项目改动

本项目是基于 **[OK-WW（ok-oldking/ok-wuthering-waves）](https://github.com/ok-oldking/ok-wuthering-waves)** 二次开发的非官方 macOS 派生版本。
原有任务、角色逻辑、图像识别与项目结构来自 OK-WW 及其贡献者；本仓库不将这些成果标为独立原创。
本项目不是上游作者发布的官方 macOS 版本，也不是《鸣潮》官方产品。

| 组成 | 上游项目 | 本次配套仓库 |
| --- | --- | --- |
| 游戏任务与识别 | [ok-oldking/ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) | [Junsheng-He-Life/ok-wuthering-waves](https://github.com/Junsheng-He-Life/ok-wuthering-waves) |
| 自动化框架 | [ok-oldking/ok-script](https://github.com/ok-oldking/ok-script) | [Junsheng-He-Life/ok-script](https://github.com/Junsheng-He-Life/ok-script) |

macOS 派生版本主要增加与调整：

- ScreenCaptureKit 采集与 Quartz 前台输入、Retina 坐标和窗口变化保护。
- 面向刷取的桌面界面、当前队伍检查、限额消费、共享账本和异常结果核对。
- 队伍切换与部分角色操作、声骸和培养材料流程。
- 配套源码安装器、固定依赖、可核验的发布清单与公开离线测试。

两个仓库原始 `LICENSE.txt` 随源码和配套包保留，内容为 GNU Affero General Public License v3。
原有源码中的作者及版权声明继续保留。第三方依赖保留各自的许可与归属；Python 包安装时取得的依赖不包含在本源码 ZIP 中。

发布使用两个仓库同名 `v0.1.0-beta.1` 标签。配套包根目录 `release-manifest.json` 记录实际源码提交、每个文件的 SHA256 和整个发布快照标识。
识别素材仅保留运行所需的标注区域及原坐标，未标注画面与 PNG 私有元数据不进入新发布素材。

感谢 OK-WW、OK-Script 的原作者及所有贡献者。
