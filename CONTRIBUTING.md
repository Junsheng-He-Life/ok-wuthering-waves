# 贡献指南

本 fork 维护 OK-WW 的 macOS 内测适配。问题、功能建议和 PR 请提交到 [Junsheng-He-Life/ok-wuthering-waves](https://github.com/Junsheng-He-Life/ok-wuthering-waves)：[Issues](https://github.com/Junsheng-He-Life/ok-wuthering-waves/issues) · [Pull requests](https://github.com/Junsheng-He-Life/ok-wuthering-waves/pulls)。

## 开发环境与测试

使用 **Python 3.13**，按 [开发与公开测试说明](docs/development.md) 安装依赖。应用仓库与配套 [ok-script fork](https://github.com/Junsheng-He-Life/ok-script) 必须相邻，并使用相同发布标签；本轮配套标签为 `v0.1.0-beta.1`。跨仓库修改请在 PR 中注明对应提交或标签。

在本仓库目录运行公开离线测试：

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
PYTHONPATH=../ok-script:. .venv/bin/python scripts/test_beta_public.py
```

公开套件使用合成观测、临时文件和模拟输入，不要求启动游戏。记录实际执行的测试、通过或跳过数量；离线结果不能代替真实游戏、其他账号或其他显示器的验证。额外测试依赖和重新打包方式见 [docs/development.md](docs/development.md)。

## 提交修改

- 保持 PR 范围清晰，说明解决的问题、修改后的行为及适用范围。
- 说明测试命令、结果和仍未验证的部分。涉及屏幕、识别或角色行为时，注明相应画面条件与队伍条件。
- 问题报告优先附面板导出的脱敏诊断包。不要提交个人配置、原始日志、全屏截图、原始录屏、账号信息、UID、特征码、令牌或凭据。
- 识别回归素材应只保留必要区域，清除账号信息与图片元数据，并验证净化后的测试仍能运行。不要将维护者私人截图作为公开测试前提。

可以直接在本 fork 提交 Issue 或 PR，并按模板填写复现与验证信息。

## 上游归属

本项目源自 [ok-oldking/ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves)，框架源自 [ok-oldking/ok-script](https://github.com/ok-oldking/ok-script)。这些链接用于标明上游来源；本 fork 的提交入口为上方的 Junsheng-He-Life 仓库。保留原作者归属及适用许可证，移植上游改动时附原提交或 PR 链接。
