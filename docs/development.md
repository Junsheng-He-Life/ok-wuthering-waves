# macOS 内测版开发与公开测试

本页对应两个仓库的配套标签 `v0.1.0-beta.1`。公开测试使用合成观测、临时文件和模拟输入，不要求游戏运行，不使用个人截图，也不验证真实账号的战斗表现。

## 获取配套源码

需要 Apple Silicon Mac、macOS 14 或更新版本、Python 3.13、Git 和 Xcode Command Line Tools。系统下限不代表所有 macOS 版本均已实机验收。两个仓库必须相邻，并使用相同的发布标签：

```bash
mkdir ok-ww-beta-source
cd ok-ww-beta-source
git clone --branch v0.1.0-beta.1 --depth 1 https://github.com/Junsheng-He-Life/ok-script.git
git clone --branch v0.1.0-beta.1 --depth 1 https://github.com/Junsheng-He-Life/ok-wuthering-waves.git
cd ok-wuthering-waves
python3.13 scripts/bootstrap_macos.py
```

安装器在本项目 `.venv` 中安装锁定运行依赖。它不会启动游戏、创建账号记录或设置系统权限。公开源码没有包根 `release-manifest.json` 时，安装器按开发 checkout 处理；从 Release ZIP 解压的版本则会核对其文件哈希。不要把旧 ZIP 的 manifest 放到修改后的源码旁边。

## 运行公开离线测试

测试依赖与游戏运行依赖分开安装：

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
PYTHONPATH=../ok-script:. .venv/bin/python scripts/test_beta_public.py
```

默认先运行本项目十个公开测试模块，再用独立子进程运行配套框架的三个测试模块：

2026-10-31 在发布 checkout 的离线验证结果：应用子集 **111 项通过、0 项跳过**；框架子集 **49 项通过、1 项权限探针排除**。这 160 项结果只对应本页的公开范围。

| 本项目公开子集 | 验证内容 |
| --- | --- |
| `TestDesktopPanel`、`TestDesktopEnvironment` | 面板布局、参数、进程协议、快捷键协议、启动诊断 |
| `TestDesktopUserState`、`TestDesktopClaimReconciliation` | 合成账号记录、脱敏、未确认消费保护与恢复幂等性 |
| `TestDesktopPreflight` | 新观测要求、角色身份、等级、世界等级及实验选项门槛 |
| `TestBetaPackage` | 模板 ROI 净化、发布文件哈希、安装条件 |
| `TestMacSession`、`TestMacViewport`、`TestMacWindowSelection`、`TestUltrawide` | 控制器互斥、像素/点换算、标题栏、超宽坐标与窗口选择 |

框架子集为 `test_macos_geometry.py`、`test_start_controller_errors.py`、`test_macos_backend.py`。会明确排除原生 helper 权限探针 `native_helper_builds_and_reports_boolean_permissions`，因此不会请求录屏权限或连接游戏。几何测试使用假进程与合成图像；它们不等于跨显示器实机验收。

两个部分均在临时工作目录运行，配置、日志和 pytest 缓存不会写入发布 checkout。应用部分先移除真实设备配置，再导入测试；框架独立进程避免应用视口补丁影响通用后端测试。可单独运行：

```bash
PYTHONPATH=../ok-script:. .venv/bin/python scripts/test_beta_public.py --app-only
PYTHONPATH=../ok-script:. .venv/bin/python scripts/test_beta_public.py --backend-only
```

不要将全仓库 `unittest discover` 当作本版本的公开验收入口。上游历史测试保留在仓库中，其中部分需要额外模板、截图或特定平台。开发记录中的完整 **620 项**回归是在维护者环境使用历史保存帧和额外测试模块完成的；这些私有输入没有随源码公开，因此不能宣称该历史结果能由公开子集完整重现。运行脚本会输出本次实际执行和跳过的数量。

真实编号已替换为合成测试数据。不要为了补齐历史测试而提交 `configs/`、`logs/`、原始录屏、全屏截图或带账号信息的素材。公开识别资产保留原画布尺寸和标注 ROI，其他像素清空；新的保存帧测试需要单独审查、净化和回归验证。

## 从公开源码重新打包

公开净化模板可以再次导出，不需要维护者的原始截图。打包脚本与净化脚本均随源码提供：

```bash
PYTHONPATH=../ok-script:. .venv/bin/python scripts/build_macos_beta.py \
  --output ../dist/ok-ww-macos-beta-0.1.0-beta.1 \
  --version 0.1.0-beta.1
```

输出包含两个相邻项目、启动入口及新的 `release-manifest.json`，并生成同名 ZIP。已有输出不会被覆盖；再次构建请使用新的输出目录。manifest 记录两个源码提交、当前工作树状态及文件 SHA256。构建时间等元数据会变化，因此重新打包不承诺整个 ZIP 字节级一致；运行源码和模板 ROI 可按各文件哈希核对。

修改后请先完成公开测试，再对两个配套提交重新生成发布包。不要使用 `setup.py` 或通用 Windows 依赖文件替代本页的 macOS bootstrap 流程。
