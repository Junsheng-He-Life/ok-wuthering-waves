# OK-WW macOS 实机移植与排错记录

日期：2026-07-25
状态：macOS 前台捕获与输入链路已跑通，自动拾取已由用户实机确认成功
涉及项目：

- `/Users/yourname/Documents/Games/ok-script`
- `/Users/yourname/Documents/Games/ok-wuthering-waves`

> 本文记录本轮对话中已经完成和验证的工作。总体设计仍参见
> [`docs/macos-port-plan.md`](./macos-port-plan.md)；该方案中“尚未实机验证”的旧状态，
> 以本文的最新实机结果为准。

本轮后续专项记录：

- [`material-acquisition-snapshot-2026-07-25.md`](./material-acquisition-snapshot-2026-07-25.md)：
  当前培养目标、素材获取大类、地区入口与页面可确认状态。
- [`macos-pitfalls-2026-07-25.md`](./macos-pitfalls-2026-07-25.md)：
  误点击、菜单循环、窗口捕获、权限、素材等价性等实机踩坑。
- [`game-ui-hotkeys-calibration-2026-07-25.md`](./game-ui-hotkeys-calibration-2026-07-25.md)：
  游戏热键、界面结构、OCR 区域和 `1920 × 1080` 坐标校准。

## 1. 当前结论

目前已经确认以下完整链路可用：

1. OK-WW GUI 可以在 macOS 启动。
2. 可以识别原生 Mac 版《鸣潮》窗口。
3. 可以通过 ScreenCaptureKit 连续捕获 `1920 × 1080` 游戏画面。
4. 启动任务时可以把《鸣潮》切回前台。
5. 可以通过 Quartz `CGEvent` 向前台游戏发送键盘和鼠标输入。
6. 已实机验证打开、关闭“索拉指南”等操作。
7. 已实机验证自动拾取普通大世界物品成功。

macOS 输入后端目前是“前台模式”：任务执行时《鸣潮》必须位于前台。它不会向后台
游戏窗口定向发送输入。

## 2. 启动方式

先启动 Mac 版《鸣潮》并进入游戏，再在终端运行：

```bash
cd "/Users/yourname/Documents/Games/ok-wuthering-waves"
PYTHONPATH="../ok-script:$PWD" ../ok-script/.venv313/bin/python main.py
```

代码修改后必须关闭并重新启动 OK-WW；当前 Python 进程不会自动热重载。

开发模式下，本轮实际查看的日志文件是：

```text
/Users/yourname/Documents/Games/ok-wuthering-waves/logs/ok-script.log
```

查看最新日志：

```bash
tail -n 100 "/Users/yourname/Documents/Games/ok-wuthering-waves/logs/ok-script.log"
```

## 3. macOS 后端实现

### 3.1 原生辅助程序

`ok-script/ok/platform/macos/native_helper.swift` 提供：

- Screen Recording 与 Accessibility 权限检查；
- ScreenCaptureKit 窗口枚举；
- 单帧截图；
- 连续 BGRA 帧流；
- 激活指定应用；
- Quartz 键盘、鼠标、滚轮和拖动事件。

`ok-script/ok/platform/macos/helper.py` 会在首次使用时调用 `swiftc` 编译辅助程序，
默认缓存到：

```text
/Users/yourname/Documents/Games/ok-script/cache/macos/ok-macos-helper
```

Swift 源文件更新时间晚于缓存程序时，会自动重新编译。

### 3.2 窗口发现与几何

`ok-script/ok/platform/macos/window.py` 实现 `MacWindow`：

- 优先按应用拥有者名称识别 `Wuthering Waves` 或 `鸣潮`；
- 保存窗口 ID、PID、bundle ID、位置和尺寸；
- 选择当前活动、可见且面积合适的游戏窗口；
- 处理 Retina 捕获像素到 macOS 全局 point 坐标的换算；
- 支持将游戏应用切到前台；
- 使用非阻塞刷新锁，防止多个线程同时运行 `list --all`。

实机识别到的关键信息：

```text
device: macos
real_hwnd: 8644
bundle_id: com.kurogame.wutheringwaves.global
resolution: 1920x1080
```

### 3.3 连续画面捕获

`ok-script/ok/device/capture_methods/macos.py` 实现
`MacScreenCaptureMethod`：

- 使用 ScreenCaptureKit 连续流，不为每帧重新启动进程；
- 校验帧头、宽高、每行字节数和载荷长度；
- 去除 BGRA alpha 通道及每行 padding，输出 NumPy BGR 图像；
- 保留最新帧供任务线程读取；
- 健康的捕获流不再重复枚举窗口。

### 3.4 前台输入

`ok-script/ok/device/interaction_methods/macos.py` 实现
`MacForegroundInteraction`：

- 支持按键点击、按下和释放；
- 支持鼠标移动、点击、按下、释放；
- 支持滚轮和拖动；
- 支持文本输入；
- 开始任务时激活游戏；
- 游戏不在前台时拒绝发送输入，避免误操作其他应用。

## 4. 跨平台兼容修改

为避免 macOS 导入或执行 Windows 专用 API，完成了以下处理：

- `DeviceManager` 增加 macOS 设备、捕获和输入后端选择。
- 捕获与输入模块根据 `sys.platform` 条件导入。
- `pywin32`、`pycaw`、`PyDirectInput` 等依赖限制为 Windows 安装。
- Windows DPI、DWM 强调色、Windows 原生事件仅在 Windows 调用。
- Windows 全局热键仅在 Windows 注册。
- 非 Windows 平台不显示当前仅支持 Windows 的计划任务页。
- 截图标注字体不再强制读取 `WINDIR`，macOS 使用系统中文字体。
- 光标位置读写增加非 Windows 实现。
- macOS 默认关闭 OpenVINO 与 NPU OCR 参数，使用 ONNX OCR CPU 路径。
- Windows 专用测试在非 Windows 平台显式跳过。
- Qt `offscreen` 下会触发 `qframelesswindow` 原生崩溃的测试在 macOS 跳过。

## 5. 本轮实机问题与修复

### 5.1 GUI 启动时调用 Windows API

症状包括：

- 缺少 `WINDIR`；
- `ctypes.windll` 在 macOS 不存在；
- Windows DWM、全局热键和计划任务组件被无条件加载。

处理：

- 增加平台判断；
- Windows 模块改为条件导入；
- macOS 使用可用的系统字体；
- macOS 不初始化 Windows 专用 GUI 功能。

结果：OK-WW GUI 可以正常启动。

### 5.2 启动任务后游戏没有自动回到前台

原因：

任务执行器启动前，没有统一调用当前输入后端的 `on_run()`。

处理：

`ok-script/ok/gui/StartController.py` 在执行器启动前调用交互后端的
`on_run()`。对于 macOS，该调用会通过辅助程序激活《鸣潮》。

成功日志：

```text
StartController:Interaction backend prepared for task execution
```

结果：任务启动时可以自动把游戏切回前台。

### 5.3 `ok-macos-helper list --all` 反复超时

症状：

```text
macOS window refresh failed:
Command '[.../ok-macos-helper, list, --all]' timed out after 10 seconds
```

原因：

- 捕获线程、窗口轮询线程和任务线程可能同时刷新窗口；
- 健康捕获流也会重复执行窗口枚举；
- 多个 ScreenCaptureKit 枚举进程并发后出现阻塞和超时。

处理：

- `MacWindow` 增加非阻塞 `_refresh_lock`；
- 同一时刻只允许一个窗口枚举；
- 健康的 ScreenCaptureKit 流直接复用，不再重复刷新窗口。

结果：消除了本轮测试中的连续 `list --all` 超时。

### 5.4 启动初期短暂显示未连接

曾出现：

```text
Game window is not connected ScreenCaptureKit_0x0
```

或首次已经获得尺寸但尚未获得可用帧：

```text
Game window is not connected ScreenCaptureKit_1920x1080
```

这是连续捕获流启动与首帧到达之间的短暂状态。后续日志出现：

```text
capturing frame (1920, 1080)
FeatureSet: Width and height changed from 0x0 to 1920x1080
```

即表示捕获已经建立，可以继续启动任务。

### 5.5 自动拾取启用但没有发送 F

日志只显示：

```text
TaskEnable task:enabled task <src.task.AutoPickTask.AutoPickTask ...>
```

却没有拾取动作。实际存在两层 UI 偏移问题。

#### 第一层：F 提示搜索框过窄

模板预期位置约为 `x = 1220`，实际 Mac 截图中的 F 提示约为 `x = 1179`。
旧搜索范围约为 `x = 1214–1247`，因此匹配不到。

离线检查结果：

- 全画面 F 模板置信度约 `0.96`；
- F 白色像素比例约 `0.647`；
- 说明模板和颜色判断本身正常，问题是搜索位置。

处理：

`BaseWWTask.f_search_box` 的水平范围由模板附近的小范围扩展为模板宽度左右各
3 倍。`1920 × 1080` 下的新范围为：

```text
x=1160, y=445, width=140, height=150
```

#### 第二层：大世界队伍 UI 识别失败

自动拾取在寻找 F 之前会先调用 `in_team_and_world()`。Mac 截图中的角色 UI
相对模板同时发生水平和垂直偏移：

- `char_2_text`：实际约 `(1693, 366)`，置信度约 `0.926`；
- `char_3_text`：实际约 `(1692, 494)`，置信度约 `0.929`；
- 模板预期横坐标约为 `1738`。

原默认容差只有屏幕尺寸的 `0.002`，水平方向约 4 像素，无法覆盖约 45 像素的
偏移。结果是自动拾取每轮都在队伍状态检查处直接返回。

处理：

- 队伍角色 UI 的水平和垂直搜索容差调整为屏幕尺寸的 `0.03`；
- 自动拾取真正发送按键时增加日志：

```text
pickup prompt detected, sending F
```

结果：用户已在实机确认自动拾取成功。

### 5.6 `executor is paused sleep` 的含义

启动时可能短暂出现：

```text
TaskExecutor:executor is paused sleep
```

本轮日志中该行之后继续加载了 FeatureSet，说明执行器已经继续运行。它不是本次
自动拾取失败的根因；真正的根因是队伍 UI 与 F 提示的位置偏移。

## 6. 主要修改文件

### `ok-script`

- `ok/platform/macos/native_helper.swift`
- `ok/platform/macos/helper.py`
- `ok/platform/macos/window.py`
- `ok/device/capture_methods/macos.py`
- `ok/device/interaction_methods/macos.py`
- `ok/device/DeviceManager.py`
- `ok/device/capture.py`
- `ok/device/capture_methods/__init__.py`
- `ok/device/interaction_methods/__init__.py`
- `ok/gui/StartController.py`
- `ok/gui/MainWindow.py`
- `ok/gui/debug/Screenshot.py`
- `ok/gui/debug/DebugTab.py`
- `ok/gui/start/StartCard.py`
- `ok/util/window.py`
- `ok/__init__.py`
- `requirements.txt`
- `setup.py`
- `tests/test_macos_backend.py`
- `tests/test_start_controller.py`
- 若干 Windows-only 测试的平台跳过条件

### `ok-wuthering-waves`

- `config.py`：增加 macOS 设备配置和 OCR 参数分流。
- `src/task/BaseWWTask.py`：扩大 F 提示与队伍 UI 的搜索容差。
- `src/task/AutoPickTask.py`：增加实际发送 F 的可观察日志。
- `tests/TestFeatureSet.py`：增加 Mac UI 偏移回归测试。
- `scripts/macos_probe.py`：权限、窗口、截图和输入探针。
- `docs/macos-port-plan.md`：macOS 移植总体设计。
- `docs/macos-debug-session-2026-07-25.md`：本文。

## 7. 测试记录

### 自动化测试

`ok-script`：

- macOS 窗口选择；
- Retina 坐标换算；
- BGRA alpha 与行 padding 处理；
- 健康捕获流不重复枚举窗口；
- 前台输入保护；
- macOS 权限返回格式；
- macOS 截图字体；
- Windows 模块导入保护；
- 启动执行器前激活交互后端；
- 完整测试集通过，Windows/Qt 平台专用测试按条件跳过。

`ok-wuthering-waves`：

```bash
PYTHONPATH=../ok-script:. ../ok-script/.venv313/bin/python \
  -m unittest tests.TestFeatureSet
```

结果：

```text
Ran 3 tests
OK
```

### 实机测试

| 项目 | 结果 |
| --- | --- |
| 识别《鸣潮》窗口 | 通过 |
| ScreenCaptureKit `1920 × 1080` 连续捕获 | 通过 |
| 启动任务自动切回游戏前台 | 通过 |
| 打开和关闭索拉指南 | 通过 |
| 普通大世界自动拾取 | 通过 |
| 连续窗口枚举不再超时 | 本轮通过 |

## 8. 权限与探针

macOS 需要向启动 OK-WW 的终端或最终应用授予：

- 系统设置 → 隐私与安全性 → 屏幕与系统音频录制；
- 系统设置 → 隐私与安全性 → 辅助功能。

检查权限和窗口：

```bash
cd "/Users/yourname/Documents/Games/ok-wuthering-waves"
PYTHONPATH="../ok-script:$PWD" ../ok-script/.venv313/bin/python \
  scripts/macos_probe.py
```

请求系统弹出权限提示：

```bash
PYTHONPATH="../ok-script:$PWD" ../ok-script/.venv313/bin/python \
  scripts/macos_probe.py --prompt-permissions
```

保存单帧截图：

```bash
PYTHONPATH="../ok-script:$PWD" ../ok-script/.venv313/bin/python \
  scripts/macos_probe.py --snapshot screenshots/macos-probe.png
```

## 9. 下一步建议测试

建议按以下顺序继续：

1. 自动对话：普通对话连续跳过、对话选项、退出对话。
2. 自动登录：登录页识别、点击进入游戏、月卡弹窗。
3. 自动战斗：方向键、技能键、鼠标按住与释放。
4. 一次性日常任务：地图、索拉指南、传送和奖励领取。
5. 不同分辨率：`2560 × 1440`、`1600 × 900`、`1280 × 720`。
6. Retina 与非 Retina 外接显示器。
7. 多显示器、不同桌面 Space、窗口被遮挡和最小化。
8. 长时间运行，观察窗口枚举、捕获流和输入是否稳定。

每次测试应记录：

- 操作前游戏所在界面；
- 是否成功自动回到前台；
- 画面分辨率；
- 预期动作与实际动作；
- 对应的 `logs/ok-script.log` 片段；
- 失败时的截图。

## 10. 当前限制

- 输入只能安全地发送给当前前台游戏。
- 窗口最小化或切换到其他 Space 时，捕获和输入状态仍需继续验证。
- macOS 原生 GUI 必须在正常登录桌面会话测试，Qt `offscreen` 不能替代。
- 自动任务中的部分模板仍可能存在 Windows 与 Mac UI 坐标差异，需要按实机截图逐项调整。
- 当前工作区包含多项尚未提交的修改；提交前应分别检查
  `ok-script` 与 `ok-wuthering-waves` 的 diff，避免混入无关改动。
