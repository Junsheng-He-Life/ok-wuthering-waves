# 角色培养材料自动刷取

## 启动方式（macOS 源码版）

先启动 Mac 版《鸣潮》并进入大世界，然后在终端运行：

```bash
cd /Users/yourname/Documents/Games/ok-wuthering-waves
PYTHONPATH="../ok-script:$PWD" ../ok-script/.venv313/bin/python main.py
```

任务执行时《鸣潮》必须保持在前台。代码修改后必须完全退出并重新启动 OK-WW；
当前 Python 进程不会热重载。

## 使用方法

程序中现在有独立任务 `Character Material Farming`，Daily Task 的
`Which to Farm` 也新增并默认选择了 `Character Materials`。

主要配置：

- `Cultivation Target`：填写素材获取页显示的完整角色名，例如
  `秧秧·玄翎`。如果只想沿用游戏内已选目标，填写
  `Use current in-game target`。
- `Character Material Type`：
  - `Auto (Target Avatar)`：使用培养目标头像定位角色关联关卡；
  - `Resonator EXP`：刷共鸣者经验；
  - `Weapon & Skill`：刷该角色的武器与技能素材。
- `Fallback Stage Name`：仅在目标头像识别失败时使用的关卡名备用值。它不是
  材料名，正常情况下留空。
- `Save Combat Frames for Debug`：默认关闭。开启后只在材料副本的战斗期间以
  `5 Hz` 保存最新画面；战斗结束或任务异常退出时自动停止。

调试帧保存到
`/Users/yourname/Documents/Games/ok-wuthering-waves/screenshots/character_material_combat_frames`。
文件名以包含毫秒的时间戳开头，例如
`11-50-02.123_frame_original.png`。截图通过现有异步写入队列保存，不会在战斗输入
线程中执行 PNG 编码；由于记录的是识别循环最近取得的画面，极短时间内可能出现相邻
文件内容相同。

首次使用建议单独运行 `Character Material Farming`，确认角色名和副本选择正确后，
再交给 Daily Task 调度。

本次爱弥斯实机使用的配置是：

```text
Cultivation Target: Use current in-game target
Character Material Type: Weapon & Skill
Fallback Stage Name:
```

`Use current in-game target` 是程序识别的完整特殊值，需要原样填写。只想用 OK-WW
单独刷材料时，直接运行 `Character Material Farming`，不需要按 Daily。两者的停止
条件不同：

- 独立任务会持续刷到结晶波片不足 40；
- Daily Task 只负责满足当天累计消耗 180 波片的目标。

## 2026-07-26 当前状态：主流程已跑通，进入战斗优化阶段

### 已验证的完整流程

当前已经实机跑通以下主链路：

1. 沿用或识别游戏内培养目标；
2. 进入“素材获取 → 凝素领域”；
3. 精确找到爱弥斯对应的 `荒萋旧殿（直接挑战）`；
4. 依次点击“单人挑战”和队伍页“开启挑战”；
5. 进入副本，等待控制恢复，以 W 短脉冲找到并按下 F；
6. 识别固定队伍 `Aemeath, Changli, Mornye`，其中第 2 槽是长离；
7. 按 `爱弥斯 → 长离 → 莫宁` 循环战斗；
8. 每个角色只有在实时协奏环连续两帧判满后才换人；
9. 战斗结束后领取奖励，并继续依据剩余波片决定是否复刷。

12:47--12:49 的实机运行完成了多轮三人轮转并正常结束战斗；后续 13:07 的运行又
验证了爱弥斯强化 E、长离第一次 R、满协奏换人和莫宁行动。长离无效 R 试按改为
有界确认后，用户随后确认整体流程已经跑通。当前目标已从“修通流程”切换为
“提高每个角色决策的果断程度、连招质量和容错”。

### 已处理问题、根因和处理步骤

| 问题 | 根因 | 已实施处理 | 当前状态 |
| --- | --- | --- | --- |
| 素材入口可能点到邻近关卡 | 只按恢复后的屏幕纵坐标点击 | 以培养目标头像、关卡名、掉落指纹和按钮类型共同定位；找不到精确项就停止 | 已实机验证 |
| 进本后找不到 F | macOS 长按 W 的实际移动不稳定 | 等待控制恢复后，以 0.25 秒 W 短脉冲前进，最多 8 秒 | 已实机验证 |
| 第 2 槽误认为莫宁 | 头像模板弱匹配和旧缓存提示 | 爱弥斯材料资料固定为 `Aemeath, Changli, Mornye`，第 2 槽权威指定长离 | 已实机验证 |
| 切人后战斗提前结束 | 切人动画会让队伍 UI 短暂消失 | 只有队伍 UI 连续消失超过超时才认为离开战斗 | 已实机验证 |
| 长离刚上场就切走 | 快速角色代码一次动作后立即请求换人 | 材料任务在统一换人入口检查实时协奏环；未满则留场并继续下一轮角色代码 | 已实机验证 |
| 满协奏仍记录 `current_con 0` | 新版协奏环有刻度缺口，旧算法要求凸闭合连通轮廓 | 保留旧检测，并为材料战斗加入稀疏刻度环颜色密度检测；换人前连续两帧确认 | 已实机验证 |
| 莫宁切入后看似停住 | 队伍 UI 过渡、R 动画和鼠标重击模板搜索范围不足 | 放宽 `mouse_forte` 水平搜索范围；地面/空中优先重击，E 可用时直接按，R 动画正常等待 | 已实机验证 |
| 所有人重击不触发 | 旧爱弥斯重击条件实际检测的是敌人锁定标记；莫宁模板峰值落在搜索框外 | 爱弥斯分别检测人形重击模板和机甲青色 Forte；莫宁扩大搜索范围 | 已实机验证 |
| R/Q 对调 | 画面位置到逻辑热键的映射写反 | `Echo Key=q`、`Liberation Key=r` | 已实机验证 |
| 爱弥斯连续重击、强化 E 生成慢 | 机甲 Forte 高亮在松开重击后仍不消失，代码立即重复长按；快速普攻又容易被动画吞掉 | 重击尝试增加 2 秒间隔；松开后等待 0.3 秒并明确输入 4 次普攻；开场改为 4 次、0.12 秒间隔 | 代码和定向测试通过，继续观察实机连招质量 |
| 长离 R 亮但不放 | 新版橙色 R 没有旧检测要求的白色像素 | 对橙色且无冷却数字的 R 做一次试按，并在 0.4 秒内确认动画或冷却 | 第一次 R 已实机释放 |
| 长离第二次切入完全不动 | 第一次 R 已消耗能量后，橙色外观仍保留；“无冷却数字”误判为可用，代码连续按 R 到技能超时 | R 兜底改为单次试按；无响应立即恢复 E/普攻，失败后 2 秒内不重试 | 代码和 42 项定向测试通过；用户确认整体流程已跑通 |
| 缺少逐帧证据 | 日志只能说明进入了哪个分支，不能确认游戏画面和技能图标 | 增加可选 `Save Combat Frames for Debug`，战斗期间异步保存 5 Hz 时间戳帧 | 已实机验证 |

### 当前仍需优化的问题

以下项目不再阻塞主流程，但适合作为下一阶段的优化顺序：

1. **长离第二轮 R 策略继续观察。**
   当前已不再阻塞流程。后续确认无能量时日志只出现一次
   `Changli orange R candidate: press once and verify`，随后出现
   `R probe had no effect; resume E and normal attacks`，长离应立即继续 E/普攻；
   真正可用时则应进入 `click_liberation end`。
2. **爱弥斯普攻与强化 E 节奏。**
   检查每次 `heavy follow-up: 4 normal attacks` 后，画面是否实际打出完整普攻串，
   以及 `aemeath_e1/e2` 是否稳定出现。若仍吞键，优先调整重击后的恢复等待和普攻
   间隔，不要再次放宽重击检测阈值。
3. **莫宁动作效率。**
   当前日志中可能连续出现多次 `Mornye resonance ready: press E immediately`；
   需要区分 E 确实可连续释放、动画期间状态未刷新，还是可用检测过宽。优化时应加入
   成功确认或短重试间隔，而不是简单延长整轮时间。
4. **协奏检测的泛化。**
   稀疏环阈值来自当前 1920×1080、三名火属性角色的实机帧。两帧确认已经降低特效
   误报，但未来更换分辨率、元素或队伍时必须重新保存满/未满样本并校准。
5. **调试帧磁盘占用。**
   1920×1080 PNG 以 5 Hz 保存时单场可产生数百 MB。问题定位完成后应关闭选项；
   后续可增加按场次目录、数量上限或自动保留最近一场的清理策略。
6. **耗尽波片后的收尾页面。**
   已有运行在领取完成后记录
   `world verification failed on macOS; no Esc was sent from an unknown page`。
   它不影响已完成的战斗和领取，但需要单独保存结束页面帧，再优化回到大世界的判断。

### 后续优化的标准处理步骤

每次只优化一个角色或一个判断，使用下面的固定流程，避免多个改动互相掩盖：

1. 完全退出并重新启动 OK-WW，确保 Python 载入最新代码；
2. 只运行 `Character Material Farming`，不要同时启用 `Auto Combat`；
3. 开启 `Save Combat Frames for Debug`，完整跑一场；
4. 记录用户看到问题的精确时间，例如 `13:07:58`；
5. 用日志建立“切入角色 → 识别状态 → 发送按键 → 动画/冷却确认 → 换人”的时间轴；
6. 查看问题前后至少 1 秒、5 Hz 保存的完整帧，确认 UI 状态，不只依赖日志文字；
7. 明确区分“检测错”“按键没发”“按键被动画吞掉”“技能无能量/冷却中”；
8. 在角色类中做有界、可退出的修改，所有视觉兜底都必须包含确认和重试间隔；
9. 增加纯逻辑定向测试，运行 `py_compile` 和 `git diff --check`；
10. 重启程序实机复核，并把新时间点、结论和验收状态补回本文档。

当前常用检查命令：

```bash
cd /Users/yourname/Documents/Games/ok-wuthering-waves
tail -n 800 logs/ok-script.log
rg "Aemeath|Changli|Mornye|switch_next_char|Concerto|click_liberation" \
  logs/ok-script.log
```

不要运行会初始化完整 GUI 截图服务的整个 `TestChar` 测试文件作为日常验证；macOS
沙箱下它可能启动捕获后异常退出。当前安全的定向验证是
`tests.TestCharacterMaterialTask` 和 `tests.TestCombatSwitch`，再配合相关文件的
`py_compile`。工作区包含大量用户现有修改，不要使用 `git reset --hard` 或回滚
无关文件。

## 当前内置角色资料

| 角色 | 自动类别 | 截图中观察到的目标关卡 |
| --- | --- | --- |
| 秧秧·玄翎 | Weapon & Skill | 陨翼云渊（关卡名） |
| 爱弥斯 | Weapon & Skill | 精确使用实机确认的 `荒萋旧殿`；未匹配到时停止，不用头像乱码或相似掉落入口替代 |

`陨翼云渊` 不作为材料名写入程序。程序用关卡行左侧的培养目标头像锁定行，再忽略
第一个通用经验奖励图标，用后续武器/技能材料图标生成掉落指纹。实际材料名称需要
进入关卡详情后才能读取。

程序会比较顶部培养目标头像与每一行的小头像，并分别记录后续各个材料图标的感知
指纹。只有头像匹配且材料图标组一致的关卡行才属于同一刷取目标。

库街区材料图鉴可用于把图标对应回正式材料名：

- 图鉴目录：<https://wiki.kurobbs.com/mc/catalogue/list?fid=1099&sid=1161>
- 截图中的银色蝴蝶图标对应
  [叠翼偏振体](https://wiki.kurobbs.com/mc/item/1446638031117959168)，其详情标注
  为迅刀角色使用的武器与技能素材。

图鉴只作为材料名称参考。自动刷取时不依赖网络，也不会用图鉴中的关卡名称覆盖游戏
当前页面；版本更新后仍以游戏内头像和掉落图标为准。

### 爱弥斯实机材料快照

2026-07-25 使用 OK-WW 的 ScreenCaptureKit 与 Quartz 输入后端切换培养目标、滚动
完整材料列表并逐项点开图标，记录到以下缺口：

| 材料 | 拥有/需要 | 缺口 |
| --- | ---: | ---: |
| 我们的选择 | 11/16 | 5 |
| 叠翼偏振体 | 3/71 | 68 |
| 忆中沉金 | 0/14 | 14 |
| 时苔茸 | 0/20 | 20 |
| 高频啸花声核 | 1/3 | 2 |
| 全频啸花声核 | 1/45 | 44 |
| 全频锐棱声核 | 2/12 | 10 |

这些数量是背包状态的实机快照，会随玩家获取或消耗材料而变化。程序将其保存在
`CHARACTER_MATERIAL_PROFILES['爱弥斯']['material_snapshot']` 中作为校准记录；
实际自动刷取仍应以运行时页面读取结果为准。

## 安全规则

程序遵循以下选择顺序：

1. 验证或选择培养目标；
2. 用培养目标头像锁定关卡行；
3. 忽略第一个通用经验图标，用后续掉落图标匹配同素材入口；
4. 在这些等价入口中优先 `直接挑战`；
5. `前往` 会进入地图后继续验证；
6. 没有可用同素材入口时停止，不会切换到其他素材。

索引后的入口会按“关卡名 + `直接挑战`/`前往` 类型”重新精确定位。如果原滚动位置
不能恢复，程序会回到列表顶部并逐页向下搜索；不会再用相同屏幕纵坐标的邻近行代替，
因此梦州的未解锁 `前往` 条目不会覆盖拉海洛已经解锁的 `直接挑战` 条目。

素材获取页不能显示背包里准确缺少的数量，因此当前任务的“刷好”含义是：

- 独立任务：持续刷所选素材，直到结晶波片不足；
- Daily Task：刷所选素材，直到当天累计消耗达到 `180`。

角色突破 Boss 和每周战歌材料的领取流程尚未纳入本任务；它们与普通 40 波片领域的
进入、复刷和周次数判断不同，在完成单独实机校准前不会冒险自动点击。

## 2026-07-25 爱弥斯实机排查记录

### 最终验证路径

本次已在 `1920×1080` 的 macOS 原生《鸣潮》中验证以下完整路径：

1. 打开“索拉指南 → 素材获取 → 凝素领域”；
2. 沿用当前培养目标“爱弥斯·预告”；
3. 扫描并索引 18 个武器与技能素材入口；
4. 跳过梦州未解锁、按钮为“前往”的入口；
5. 向下滚动，在“索拉里斯之极·拉海洛”找到已经解锁的
   `荒萋旧殿（直接挑战）`；
6. 精确恢复并选择 `荒萋旧殿（直接挑战）`；
7. 关卡详情页通过 OCR 点击“单人挑战”；
8. 队伍选择页通过模板点击“开始挑战”；
9. 进入副本后识别 F，并成功进入战斗。

梦州没开不代表对应素材完全不能刷。同一种银色蝴蝶图标材料在拉海洛存在已解锁的
“直接挑战”入口，因此必须继续向下滚动，不能只检查列表首屏。

### 本次修复的问题

- **误选邻近关卡**：旧恢复逻辑可能在滚动位置有偏差时点击同一纵坐标附近的另一行，
  曾出现索引 `荒萋旧殿`、实际点击 `余烬终课` 的情况。现在恢复时同时精确匹配
  “关卡名 + 按钮类型”，找不到就从列表顶部逐页向下扫描，绝不点击邻近行。
- **滚动与 OCR 时间差**：每次滚动后等待页面稳定再读取；扫描日志会列出每一页实际
  识别到的关卡名和“前往/直接挑战”类型。
- **两层挑战按钮**：当前界面不是一次点击就进本。第一层是关卡详情页的“单人挑战”，
  第二层是队伍选择页的“开始挑战”；两层都已分别支持模板或 OCR 识别。
- **进本后找不到 F**：原流程只发送一次最长 4 秒的 W 长按，macOS 下日志虽显示调用，
  游戏中却可能没有明显移动。爱弥斯素材任务现在会在队伍 UI 出现后额外等待 3 秒，
  再连续短按 W（每次 0.25 秒，最多 8 秒），仍找不到时保存
  `domain_entry_f_not_found` 截图并停止。

### 最后一次成功运行的关键日志

```text
indexed 18 material location(s)
restored exact material location 荒萋旧殿 (直接挑战)
click solo challenge by OCR: 单人挑战
click team-page start challenge by template
domain entry: wait 3s for character controls
domain entry: press w 32 time(s), 0.25s per press
domain entry: forward key presses found f
Chars Aemeath, Changli, Mornye
```

实机观察中没有看到明显的角色位移，但日志显示 W 短按开始约 3.5 秒后才找到 F，随后
F 交互确实触发并进入战斗。因此当前结论是“进本与开战链路已成功”，而不是出生点
立即误识别 F；macOS 下角色移动的视觉反馈仍需在后续运行中继续观察。

### 日志与失败截图

- 日志：`/Users/yourname/Documents/Games/ok-wuthering-waves/logs/ok-script.log`
- 截图目录：`/Users/yourname/Documents/Games/ok-wuthering-waves/screenshots`
- 找不到素材入口、挑战按钮或副本 F 时，先保留失败时的页面，不要手动切换界面，
  再结合日志末尾和对应自动截图定位。

## 2026-07-26 macOS 战斗调度历史技术交接

这一节保留排查过程中当时的结论，部分“当前问题”已经被上面的最新状态取代。
供需要追溯早期日志时参考。不要回滚工作区或用
`git reset --hard`；两个仓库都有尚未提交的用户改动。

### 当前结论

素材入口、两层挑战按钮、进本和开战已经可以完整走通。爱弥斯的普攻、两种强化 E
识别和直接按 E 已经在最新实机日志中生效。

当前最高优先级问题不是“莫宁的 `perform()` 已执行但没有出招”，而是角色切换阶段
过早结束了战斗。2026-07-26 11:18 的最新材料本日志显示：

```text
11:18:50.932 domain combat: immediate opening attack
11:18:52.374 Aemeath opening: 3 immediate normal attacks
11:18:56.562 Aemeath enhanced E visible
               (aemeath_e1, confidence=0.883): press resonance immediately
11:19:01.850 Aemeath enhanced E visible
               (aemeath_e2, confidence=0.868): press resonance immediately
11:19:03.065 switch_next_char Aemeath(MainDps) -> Changli(MainDps)
11:19:03.417 not in team while switching chars_Aemeath_to_Changli
11:19:03.443 combat_once out of combat break not in_team while switching
```

因此本轮在爱弥斯切长离的瞬间，`BaseCombatTask.switch_next_char()` 内的
`in_team()` 检查把切人动画/短暂 UI 消失当成离开战斗并抛出
`NotInCombatException`。战斗循环随后结束，长离和莫宁的 `perform()` 都没有执行。

用户之后启动的 `AutoCombatTask` 已经处于战斗结束或非正常队伍 UI 状态，因此出现
了连续错误识别：

```text
Chars Mortefi, Rover, Mortefi
Chars Rover, Rover, Yuanwu
Target enemy failed
```

这些记录不能作为莫宁角色模板失效的证据。新线程应首先修复/放宽切人瞬间的
`in_team()` 过渡判定，重新跑材料任务，确认日志真正出现 `Mornye` 的动作记录后，
再判断莫宁机制是否仍有问题。

### 已解决的问题及处理方式

#### 1. 素材入口和挑战链路

- 使用培养目标头像及材料图标索引关卡，不再只按屏幕纵坐标点击。
- 爱弥斯资料要求精确关卡 `荒萋旧殿`；不能用相似材料或邻近行替代。
- 如果当前屏幕已经看到正确的 `直接挑战`，立即选择，不再完成无意义的全列表扫描。
- 恢复入口时精确匹配“关卡名 + 按钮类型”；找不到就回顶部逐页重扫。
- 分别处理关卡详情页“单人挑战”和队伍页“开启挑战”。
- 进入副本后等待角色控制恢复，再以 0.25 秒 W 脉冲寻找 F。

最新成功链路：

```text
verified visible direct challenge 荒萋旧殿; enter immediately
click solo challenge by OCR: 单人挑战
click team-page start challenge by OCR: 开启挑战
domain entry: forward key presses found f
Chars Aemeath, Changli, Mornye
```

#### 2. 开战慢、攻击频率低

根因是每次攻击输入之前都会执行“确认离开”OCR。一次 OCR 约耗时 2 秒，而且输入
路径被串行化，导致第一次普攻和后续攻击都有明显停顿。

处理方式位于 `src/task/DomainTask.py`：

- 战斗热路径只用 `gray_confirm_exit_button` 模板检查离开确认，最多每 0.1 秒检查；
- OCR 只保留为非热路径诊断，不再阻塞每次攻击；
- `on_combat_started()` 立即发出 3 次普攻，间隔 0.04 秒；
- 保留所有按键和鼠标动作之前的 manual override 防护。

#### 3. 爱弥斯机制

保留原 OK-WW `Aemeath.perform()` 架构，并为材料任务使用较短、有界的时间预算。

当前动作逻辑：

1. 上场立即进行 3 次普攻，间隔 0.08 秒；
2. 每轮优先检查强化 E；
3. 命中 `aemeath_e1` 或 `aemeath_e2` 后直接发送物理 E，不走较慢的通用点击等待；
4. 没有强化 E 时先补一次普攻，再进行重击、R 和其他视觉/CD 检查；
5. 材料任务允许 visibly-ready 的 R 立即释放；
6. 仍保留爱弥斯原有 lib1/lib2、重击准备 lib2 和 lib2 后 3A+E 机制。

强化 E 参数：

```text
threshold = 0.60
horizontal_variance = 0.025
vertical_variance = 0.025
retry_interval = 0.45s
```

用户截图的实际匹配结果：

- 第二张截图当前角色为爱弥斯；
- 队伍头像识别：爱弥斯 0.913、长离 0.822、莫宁 0.931；
- `aemeath_e1`：0.923；
- 模板原图 3840×2160，标注框 `[3187, 1879, 120, 90]`；
- 在 1920×1080 下正确缩放为约 `[1594, 940, 60, 45]`；
- 实际命中框约 `[1602, 939, 60, 45]`；
- 旧全局位置容差 0.002 不能命中，当前 0.025 可以稳定覆盖偏移。

最新实机已经连续识别并按下两种强化 E：

```text
Aemeath enhanced E visible
    (aemeath_e1, confidence=0.883): press resonance immediately
Aemeath enhanced E visible
    (aemeath_e2, confidence=0.868): press resonance immediately
```

用户反馈：“爱弥斯的部分好很多了。”

#### 4. 莫宁机制（已实现，尚未得到新一轮完整实机验证）

`src/char/Mornye.py` 当前优先级：

1. 满协奏/满 Forte 时立即重击；
2. E 可用时直接发送物理 E；
3. 否则继续普攻；
4. 空中和地面分支都采用“重击优先于 R/E/普攻”。

预期日志：

```text
Mornye forte full on ground: heavy attack immediately
Mornye forte full in air: heavy attack immediately
Mornye resonance ready: press E immediately
```

莫宁重击使用公共 `mouse_forte` 模板：

```text
threshold = 0.60
horizontal_variance = 0.025
vertical_variance = 0.015
frame_processor = binarize_for_matching
```

第一张用户截图当前角色为莫宁。模板原图已经是 1920×1080，不需要缩放；标注框
`[1141, 978, 21, 29]`。在该截图中实际命中约 `[1123, 987, 21, 29]`，置信度
`0.859`。旧水平容差 0.002 只有约 0.193，当前容差正确。

莫宁 E 没有专属图标模板，使用公共 `box_resonance` 区域加 CD 检查。该区域的原始
标注为 3840×2160 的 `[3185, 1877, 135, 113]`，在 1920×1080 正确缩放到约
`[1592, 938, 68, 56]`。截图中的位置是正确的。

但最新材料本在莫宁 `perform()` 之前就因切人误判结束，所以“切到莫宁后不行动”
必须在修复切人过渡判定后重新验证。

#### 5. R/Q 热键颠倒

`BaseCombatTask.load_hotkey()` 曾把 Echo 和 Liberation 的识别区域写反，导致：

```text
Liberation Key q
Echo Key r
```

现已改为：

```text
Echo Key q
Liberation Key r
Resonance Key e
```

本地 `configs/Game Hotkey.json` 已恢复并经过测试。新线程运行测试后要再次检查该
文件，避免测试 teardown 把配置写空。

#### 6. macOS 弹出备忘录/其他窗口

macOS Quartz 合成的 Q 键可能继承物理或系统的 Fn 标志，从而触发系统
`Fn+Q` Quick Note（快速备忘录）。

`../ok-script/ok/device/interaction_methods/macos.py` 当前：

- 每一个键盘和鼠标 Quartz 事件都显式调用 `CGEventSetFlags`；
- 即使没有修饰键也明确写入 0，清除继承的 Fn/Command；
- 只有游戏位于前台时才发送输入；
- 无坐标战斗点击使用游戏窗口中心，不使用系统鼠标当前坐标。

已有回归测试验证 Q 的 key-down/key-up flags 都为 0。

#### 7. `ok.platform` 与 Python 标准库 `platform` 冲突

根因不是普通的同名包搜索顺序，而是导入 `ok.platform.macos` 后，父包 `ok` 的
`platform` 属性会覆盖 `ok/__init__.py` 中原先导入的标准库变量。

已在 `../ok-script/ok/__init__.py` 中把标准库改名为：

```python
import platform as py_platform
```

并使用 `py_platform.version()`。`../ok-script/tests/test_macos_backend.py` 有对应
回归测试。

#### 8. Manual override / 确认离开

目标行为：看到用户手动打开“确认离开”界面后，立刻停止所有攻击，不替用户确认，
也不再由 `AutoCombatTask` 继续接管。

当前实现：

- 每个战斗输入前检查 `gray_confirm_exit_button`；
- 命中后抛出 `ManualDomainExitRequested`；
- `DomainTask` 设置 manual-exit latch；
- `AutoCombatTask` 读取 latch 并抑制自动接管。

该逻辑已经有单元测试，但最新实机运行没有再次覆盖此路径。它仍属于需要最终实机
确认的项目。

### 当时遗留问题（已由后续章节继续处理）

1. **实机验证本轮切人修复。**
   实机队伍顺序是 `Aemeath, Changli, Mornye`，第 2 槽确实是长离。日志中的计划目标
   `Changli` 没有写错。画面最后停在莫宁，是因为切长离动画被误判为离开战斗后，
   `combat_end()` 调用了爱弥斯的 `on_combat_end()`；其收尾逻辑会优先切治疗角色，
   于是又发送数字键 `3` 切到第 3 槽莫宁。

   `BaseCombatTask.switch_next_char()` 现已允许切人动画期间短暂隐藏队伍 UI；只有队伍
   UI 连续消失超过 `switch_char_time_out` 才抛出异常。日志也会打印角色名、槽位和
   首次发送的数字键。纯逻辑回归测试覆盖“单帧消失后恢复”和“持续消失后超时”。
2. **修复后重新验证莫宁 `perform()`。**
   必须先在日志中看到上述 `Mornye ...` 动作行，再判断重击或 E 是否仍漏按。
   莫宁重击模板未命中时会每秒记录一次 `mouse_forte` 最佳置信度；如果此时 E
   被判定可用，每场战斗还会保存一次
   `mornye_forte_not_matched_*_e_ready` 截图，用于区分模板阈值问题与技能状态问题。
3. **区分材料任务结束与 AutoCombat 接管。**
   当前材料任务异常退出后，AutoCombat 在错误页面反复扫描角色，产生大量假匹配。
   可考虑在材料任务的战斗切换异常后也设置短暂抑制，避免另一个任务立即接管。
4. **实机复核 manual override。**
   确认离开对话框出现时应在下一次输入前停止，并保持停止。
5. **继续观察 macOS Quick Note。**
   flags 清零后理论上已解决；若再次发生，保留精确时间点并检查前台守卫日志。

### 下一线程建议的第一轮操作

1. 完全退出并重新启动 OK-WW，确保加载最新 Python 代码；
2. 只启动 `Character Material Farming`，不要同时启动 `Auto Combat`；
3. 复现一次爱弥斯切长离/莫宁；
4. 查看日志：

```bash
cd /Users/yourname/Documents/Games/ok-wuthering-waves
tail -n 500 logs/ok-script.log
```

5. 先围绕以下关键词定位：

```text
switch_next_char
not in team while switching
combat_once out of combat
Mornye
forte full
resonance ready
ManualDomainExitRequested
```

新线程可以直接这样开始：

```text
请先阅读 docs/character-material-farming.md 的
“2026-07-26 macOS 战斗调度技术交接”。最新问题是爱弥斯已经能连续识别并释放
e1/e2，但切人时 BaseCombatTask 把短暂的队伍 UI 消失误判成 not_in_team，
导致战斗在长离和莫宁 perform 之前结束。请先查看最新日志并修复切人过渡判定，
然后我自己实机测试莫宁。
```

### 相关代码与验证状态

主要文件：

- `src/task/CharacterMaterialTask.py`
- `src/task/DomainTask.py`
- `src/task/BaseCombatTask.py`
- `src/task/AutoCombatTask.py`
- `src/combat/CombatCheck.py`
- `src/char/Aemeath.py`
- `src/char/Mornye.py`
- `src/char/BaseChar.py`
- `../ok-script/ok/device/interaction_methods/macos.py`
- `../ok-script/ok/__init__.py`

相关测试：

- `tests/TestCharacterMaterialTask.py`
- `tests/TestCombatCheck.py`
- `tests/TestChar.py`
- `tests/TestKey.py`
- `../ok-script/tests/test_macos_backend.py`

最近的爱弥斯、莫宁、热键、Quartz 和 platform 针对性测试均通过，
`py_compile` 与相关 `git diff --check` 通过。没有宣称整个测试套件全部通过：
完整测试仍有缺失图片 fixture 和既有切人优先级用例等无关失败。

### 2026-07-26 12:29 协奏满环与材料战斗换人闸门

最新实机帧确认了另一个独立问题：`12-27-09.685_frame_original.png` 中莫宁
左下协奏环已经满，但 `switch_next_char` 仍记录 `current_con 0`。原因不是角色
代码没有充能，而是新版协奏环带有刻度缺口；旧 `count_rings()` 要求目标颜色构成
一个凸、闭合的连通轮廓，因此新版满环也会被判为未满。

当前实现保留旧轮廓检测，并只为材料战斗启用新版稀疏刻度环检测。1920x1080
实机样本中，长离未满帧在目标环带内有约 13--18 个火色像素，爱弥斯/莫宁满环
约 26--35 个。新检测使用分辨率无关的环带像素密度阈值，并在真正换人前要求
下一帧再次判满，过滤橙色技能特效造成的单帧误报。

材料战斗现在还会在统一换人入口强制检查协奏环：

- 未满时不发送数字换人键，补一小段普攻后返回同一角色的下一轮 `perform()`；
- 满环连续两帧成立才按 `Aemeath -> Changli -> Mornye` 的顺序切换；
- 即使角色模块传入 `free_intro=True`，材料战斗仍以实时可见协奏环为准。

这会直接解决长离刚上场就切走的问题，并让莫宁在未满协奏时继续执行自己的
E、R、重击和普攻循环，而不是因为单次快速轮转结束后离场。

### 2026-07-26 12:49 爱弥斯重击循环与长离 R

12:47--12:49 的实机日志和 5 Hz 战斗帧又确认了两个角色分支问题：

- 爱弥斯的机甲重击信号在松开鼠标后仍保持高亮，旧代码把 1.2 秒等待超时当作
  “重击未执行”，因此下一轮立即再次长按。现在每次重击尝试都会进入 2 秒重试
  冷却，并在松开后明确等待 0.3 秒、输入 4 次普攻，让普攻链生成强化 E。
  每轮开场普攻也从 3 次、0.08 秒间隔调整为 4 次、0.12 秒间隔，降低动画吞键。
- 长离在 `12-48-49.557` 等帧中 R 呈橙色，但通用检测仍要求 R 框出现白色像素。
  后续实机又证明橙色外观在能量不足时也可能保留，不能单独当作可用状态。长离
  现在只对“橙色且没有冷却数字”的 R 做一次试按，并在 0.4 秒内验证是否进入动画
  或出现冷却；无响应就立即恢复 E/普攻，失败试按 2 秒内不重复，避免阻塞轮转。
  她仍保留原角色代码中三层心眼时先 E、随后 R 的顺序。

用户提供的两张校准截图：

- 莫宁：
  `/var/folders/gs/_44s63d17xb64pll70smd6800000gn/T/TemporaryItems/NSIRD_screencaptureui_u1v5wo/Screenshot 2026-07-26 at 11.01.31.png`
- 爱弥斯：
  `/var/folders/gs/_44s63d17xb64pll70smd6800000gn/T/TemporaryItems/NSIRD_screencaptureui_8Z01PR/Screenshot 2026-07-26 at 11.01.45.png`
