# 0.1.0-beta.2 开发与公开验证

Release完整附件包含两个配套项目。源码开发时把同标签的ok-wuthering-waves与ok-script克隆到相邻目录；在应用目录运行`python3.13 scripts/bootstrap_macos.py`。安装不会启动游戏。

公开测试：先在项目.venv安装`requirements-dev.txt`，再运行：

```bash
PYTHONPATH=../ok-script:. .venv/bin/python scripts/test_beta_public.py
```

也可传`--app-only`或`--backend-only`。应用子集使用临时配置和模拟输入；框架检查排除会连接原生权限helper的探针。公开测试不要求游戏或私人截图。完整历史保存帧回归属于维护者验证，不能把`unittest discover`当作公开可复现入口。

当前验证范围为GUI选择与默认预算、当前角色名单、真实Qt子进程暂停/继续/立即停止/本场后停止协议、UTF-8输出、账户初始化防清零、诊断脱敏、发布模板ROI、安装清单和macOS输入映射。运行时以实际测试数量与结果为准；通过不表示所有关卡或机器已实测。

重新打包（从完整Git checkout，需相邻框架）：

```bash
PYTHONPATH=../ok-script:. .venv/bin/python scripts/build_macos_beta.py --output ../dist/ok-ww-macos-beta-0.1.0-beta.2 --version 0.1.0-beta.2
```

导出使用白名单，不携带configs、logs、venv或原始个人截图。模板只保留标注ROI，其余像素清空；release-manifest.json记录源文件、输出文件及源码快照SHA256。输出目录和ZIP都拒绝覆盖。包内代码被修改后，请重新构建，不要伪造旧manifest。

报错流程见用户教程。新增适配前保存失败判定与可重放证据，区分请求输入、确认施放、确认通关与确认消费；不得用计时替代这些状态。
