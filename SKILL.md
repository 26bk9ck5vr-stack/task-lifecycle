---
name: task-lifecycle
description: "GSD-style 任务生命周期管理 — Discuss → Plan → Execute → Verify → Ship，完整闭环"
---

# Task Lifecycle — GSD-style 完整任务闭环

> 基于 dual-agent-loop（规划/审核）+ task-monitor（执行监控），GSD 六指令适配 Hermes 版本。

## 定位

**这不是新系统**，是 dual-agent-loop + task-monitor 的整合封装。

- dual-agent-loop 负责：规划优化、方案审核
- task-monitor 负责：执行监控、checkpoint、stale detection、recovery
- 本 skill 负责：把它们串成完整 lifecycle

## 完整生命周期

```
┌─────────────────────────────────────────────────────────────┐
│  Phase 0: Discuss                                            │
│  对齐理解 — 目标 / 约束 / 完成标准 / 风险                     │
│  产出：discuss.md（写进 Kanban task body 或独立 artifact）     │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Phase 1: Plan（复用 dual-agent-loop）                      │
│  SP 出初稿 → CC 优化 → Gemini 深度优化                      │
│  产出：plan.md / plan_cc.md / plan_gemini.md               │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Phase 2: Execute（复用 task-monitor）                      │
│  Kanban 建主任务 + N 个子任务                                │
│  每个子任务 spawn subagent 执行                              │
│  完成 → kanban_checkpoint() → stale_monitor 监控           │
│  偏差自动处理（Deviation Rules）                             │
│  产出：各子任务 artifacts + SUMBMIT.md                      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Phase 3: Verify（复用 dual-agent-loop Stage 4）             │
│  CC 走一遍验证 plan执行结果                                  │
│  小问题直接修，方向性问题打回 Phase 1                        │
│  产出：verify_result.md                                     │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Phase 4: Ship                                              │
│  方案归档 → 汇报用户                                         │
│  完成 / 保持现状                                            │
└─────────────────────────────────────────────────────────────┘
```

## Phase 0 — Discuss

**目的**：执行前对齐各方理解，防止方向性偏差传进 Plan。

**三个问题**（每次执行前必须回答）：

1. **目标是什么** — 要交付什么、可验收的标准是什么
2. **约束是什么** — 技术限制、时间、资源、不能碰的边界
3. **风险在哪** — 最可能失败的点是什么、Plan 里最难验证的是什么

**产出格式**（写入 Kanban task body 或 `~/.hermes/task-lifecycle/{task_id}/discuss.md`）：

```markdown
## Discuss — {task_id}

### 目标
...

### 约束
...

### 已知风险
...

### 对齐确认
- [ ] 所有参与者对目标理解一致
- [ ] 约束条件已确认可行
- [ ] 风险已被 Plan 阶段覆盖
```

**注意**：Discuss 不能跳过。即使任务紧急，10 分钟的讨论能避免 2 小时的返工。

## Phase 1 — Plan（复用 dual-agent-loop）

直接调用 dual-agent-loop skill：

```bash
cd ~/.hermes/dual-agent-loop
claude -p "调用 using-superpowers skill 出初稿 → 写入 plan.md"
```

**输出**：
- `~/.hermes/dual-agent-loop/plan.md` — SP 初稿
- `~/.hermes/dual-agent-loop/plan_cc.md` — CC 优化版
- `~/.hermes/dual-agent-loop/plan_gemini.md` — Gemini 最终版

## Phase 2 — Execute（复用 task-monitor）

### 入口

Plan 完成后，Hermes 分解 plan_gemini.md 为 N 个子任务，写入 Kanban：

```bash
# hermes CLI 不在 PATH，用完整路径
~/.hermes/node/bin/hermes kanban create "主任务：{task_name}"
~/.hermes/node/bin/hermes kanban create "子任务A：{subtask_desc}" --parents <parent_id>
~/.hermes/node/bin/hermes kanban create "子任务B：{subtask_desc}" --parents <parent_id>
```

> 注意：`hermes` 命令不在系统 PATH 中，必须用完整路径 `~/.hermes/node/bin/hermes`。或在 shell profile 加入 `export PATH="$HOME/.hermes/node/bin:$PATH"`。

每个子任务派发给 subagent 执行：

```bash
delegate_task(
  goal="执行子任务A：{description}",
  context={plan_gemini.md 内容 + discuss.md 内容 + artifacts 路径},
  toolsets=["terminal", "file", "web"]
)
```

### Deviation Rules（执行中自动处理）

执行时发现问题，套用以下规则，**不打断执行流程**：

**Rule 1 — 自动修 bug**
- 触发：代码不工作（错误、崩溃、逻辑错误）
- 处理：修 → 验证 → 继续
- 追踪：记录到 SUMMARY.md

**Rule 2 — 自动补关键缺失**
- 触发：缺少必要性功能（错误处理、输入校验、认证）
- 处理：补 → 验证 → 继续
- 追踪：记录到 SUMMARY.md

**Rule 3 — 自动修 blocking 问题**
- 触发：类型错误、导入失败、缺少 env var
- 处理：修 → 继续
- **不处理**：package install 失败（打 checkpoint:human-verify）

**Rule 4 — 停下来问**
- 触发：需要架构变更（新增表、换框架、破坏性 API 变更）
- 处理：STOP → 汇报 Hermes → 用户决策

### Checkpoint 写入

每个子任务完成时：

```bash
python ~/.hermes/skills/task-lifecycle/scripts/kanban_checkpoint.py \
  --task-id <id> \
  --stage <stage_name> \
  --artifacts <comma_sep_paths> \
  --next-step <next_subtask> \
  --summary <what_was_done>
```

### Stale 监控

`kanban_stale_monitor.py`（cron 每分钟调用）自动扫描：

| 场景 | 条件 | 动作 |
|------|------|------|
| A | 从未写 checkpoint + 超时 | 自动 abort |
| B | 有 checkpoint + 超时 | 通知 + 人工三选一 |

### Recovery

```bash
python ~/.hermes/skills/task-lifecycle/scripts/recovery_exec.py \
  --task-id <id> --action <resume|rollback|abort>
```

## Phase 3 — Verify

所有子任务 `status=done` 后，CC 介入：

```bash
claude -p "你是 verifier。
读：
- plan_gemini.md（原始方案）
- 各子任务的 artifacts
- SUMBMIT.md（执行结果）

验证：
1. 方案是否完整执行
2. 偏差是否被正确处理
3. 产出是否符合验收标准

输出：verify_result.md
有小问题直接修；方向性问题汇报 Hermes 打回 Phase 1"
```

## Phase 4 — Ship

```markdown
## 完成汇报

**任务**：{name}
**状态**：✅ 完成 / ⚠️ 部分完成
**产出**：{artifacts 路径}
**偏差**：{如有，记录在 SUMMARY.md}

{有提升 → "建议实装"}
{无提升 → "保持现状"}
```

## 目录结构

```
~/.hermes/task-lifecycle/
├── {task_id}/                 # 每个任务一个目录
│   ├── discuss.md              # Phase 0 产出
│   ├── plan.md                # Phase 1 产出
│   ├── plan_cc.md
│   ├── plan_gemini.md
│   ├── verify_result.md       # Phase 3 产出
│   └── SUMMARY.md             # Phase 2 产出
├── agents/                    # 原始 GSD agent 文件（下载的，未改写）
├── gsd-adapted/               # 适配后的 Hermes 专用 agent skill
│   ├── gsd-researcher.md
│   ├── gsd-researcher-domain.md
│   ├── gsd-planner.md
│   ├── gsd-executor.md
│   ├── gsd-verifier.md
│   ├── gsd-code-reviewer.md
│   └── gsd-debugger.md
├── scripts/                   # worktree-aware 版本的 checkpoint/recovery
│   ├── kanban_checkpoint.py   # schema_version=2，支持 worktree
│   └── recovery_exec.py       # 支持 worktree rollback/abort
├── references/
    └── deviation_rules.md     # 从 GSD executor 移植

task-monitor scripts（原始版本，非 worktree-aware）：
~/.hermes/skills/task-monitor/scripts/
├── kanban_checkpoint.py       # 旧版 schema_version=1
├── kanban_stale_monitor.py
├── recovery_exec.py           # 旧版，无 worktree 支持
└── verify_pipeline.py
```

## ⚠️ Pitfalls（执行陷阱）

### Phase 1: Superpowers (星火) subagent 需要 retry 机制

星火引擎对 task-lifecycle 的调用会因为并发限流报 `code: 10010, RecvFromEngineError:Engine Busy`。

**workaround**：不要用 `delegate_task` 调用星火做 task-lifecycle planning。直接用 terminal + write_file 写 plan，或者用 CC（MiniMax-M2）做 planning。

### Phase 2: CC (claude -p) 慢是正常的，等着

CC（MiniMax-M2）推理慢，超时 60s 是正常的，不要因为等了就放弃。给 CC 更长的 timeout（如 300s）让它跑完。

### Phase 3: gsd-adapted agents 需 CC 推理验证后才能用于生产

gsd-adapted agents 当前存在明确的工具映射错误，必须经过 CC 推理 review 才能实际使用：

**已知问题**：
- `gsd-executor.md`（6/10）：第 48 行混用 `grep -n`（bash 命令），但 `terminal` 工具列表中没有 grep；正确的应该用 `search_files`
- `gsd-debugger.md`（6/10）：tools 太少，缺 git/grep；`<trigger>` 引用无定义

**验证方法**：
```bash
cd /home/gato/.hermes && echo "评估 ~/.hermes/task-lifecycle/gsd-adapted/gsd-executor.md：role是否清晰、tools映射是否合理、是否有明显错误。评分1-10。" | ~/.hermes/node/bin/claude -p --dangerously-skip-permissions --allowedTools ""
```

**原则**：gsd-adapted agents 是参考材料，生产使用前必须经过 CC review，修复发现的问题。

### CC 不需要代理

CC（Claude Code/MiniMax-M2）直连 `api.minimaxi.com`（CC的直连 endpoint），不需要也不应该配置 HTTP_PROXY。

如果 CC 报 `ConnectionRefused`，检查 `~/YOUR_CLAUDE_CONFIG/settings.json` 的 `env` 字段是否配置了 `HTTPS_PROXY`/`HTTP_PROXY`，有则删掉。

---

## 新增能力（2025-05-22）

### 专属 Agent 池

task-lifecycle 现已内置 6 种 GSD 风格专业 subagent，可通过 delegate_task 加载对应 skill：

| Agent | Skill 文件 | 用途 |
|-------|-----------|------|
| researcher | `task-lifecycle/gsd-adapted/gsd-researcher.md` | 调研/查资料 |
| planner | `task-lifecycle/gsd-adapted/gsd-planner.md` | 任务分解/规划 |
| executor | `task-lifecycle/gsd-adapted/gsd-executor.md` | 执行代码任务 |
| verifier | `task-lifecycle/gsd-adapted/gsd-verifier.md` | 验证产出质量 |
| code-reviewer | `task-lifecycle/gsd-adapted/gsd-code-reviewer.md` | 代码审查 |
| debugger | `task-lifecycle/gsd-adapted/gsd-debugger.md` | 诊断问题 |

**加载方式**（在 delegate_task 的 context 中指定 skill）：
```
skill_view(name='task-lifecycle/gsd-executor')
```

### Commit 原子性（Worktree 模式）

每个子任务在独立的 git worktree 中执行，失败时只回滚当前任务，不影响主分支。

**核心流程**：
```
Task 开始 → 创建 worktree + 新分支 → 在 worktree 内执行 → 提交 commit
    ↓ 成功 → merge 到主分支
    ↓ 失败 → git checkout {commit} 回滚 worktree → 重新派发
```

**配套脚本**（位于 `~/.hermes/task-lifecycle/scripts/`）：
- `kanban_checkpoint.py`（新版）：worktree-aware，schema_version=2
- `recovery_exec.py`（新版）：支持 worktree rollback / abort 清理

**验证结果**：
- ✅ worktree 创建成功
- ✅ commit SHA 正确记录
- ✅ rollback git checkout 成功（文件被回滚删除）
- ✅ abort worktree 清理成功

---

## 已知限制

### execute_code 沙盒与 terminal 环境隔离

`execute_code` 的 Python 沙盒与宿主机文件系统隔离，无法 import 本地 Python 模块（如 `kanban_checkpoint.py` 的依赖）。调用 skill scripts 时：
- **用 `terminal()` 而非 `execute_code()`**，确保脚本在宿主机环境执行
- 沙盒内只能用 `subprocess` 调用 `python3 /path/to/script.py`，不能 `import script`

### Hermes CLI 不在 PATH
`~/.hermes/node/bin/hermes` 不在系统 PATH，调用时用完整路径。

与 task-monitor 一致的其他限制：
- `resume` 依赖 worker 是否还持有任务
- `abort` 后无法反悔

新增（已解决）：
- ~~`rollback` = `resume`（无多级回滚）~~ ✅ 已解决：worktree 模式下 git checkout commit 实现真正的多级回滚
- Discuss 阶段的对齐确认是口头承诺，无强制执行机制
- Phase 1 的 dual-agent-loop 调用需 Hermes 主动触发，无自动流转

## 验证记录（2025-05-22）

**验证目标**：task-lifecycle 全流程 + GSD 对齐的两项新增能力

**验证方法**：self-verification（实际跑 task-lifecycle 框架）

**验证结果**：

| 组件 | 验证点 | 结果 |
|------|--------|------|
| discuss | discuss.md 包含 目标/约束/风险/完成标准 | ✅ |
| gsd-adapted agents | 7个文件，内容正确可读 | ✅ |
| worktree checkpoint | schema_version=2，commit SHA 正确写入 | ✅ |
| worktree rollback | git checkout 回滚成功，文件被删除 | ✅ |
| Kanban 任务流转 | create→execute→done 正常 | ✅ |

**验证陷阱（CC 推理验证 vs 实际运行）**：
CC 和 Hermes delegate_task 是两套不同的 runtime。CC 用 `Read/Write/Bash/Grep`，Hermes 用 `read_file/write_file/terminal/search_files`。gsd-adapted agent skills 是给 Hermes 用的，工具名用 Hermes 风格是正确的。CC 推理时报"tools 名不匹配"是拿 CC 标准去量 Hermes skill，属于误报。

**已知问题**：
- Superpowers (星火)：Engine Busy (10010) 错误频繁，建议用 terminal 直接验证
- CC (claude -p)：60s 超时，建议用 `--dangerously-skip-permissions` 时单独处理

**CC 推理验证（2025-05-22）**：
- `gsd-executor.md`：**6/10** — tools 混用 `grep -n`，第 48 行需改用 `search_files`
- `gsd-debugger.md`：**6/10** — tools 太少（缺 git/grep），`<trigger>` 引用无定义

---

## 不做的事

- 不改 Hermes 核心
- 不改 dual-agent-loop skill 本身
- 不改 task-monitor skill 本身
- 不做自动 recovery（所有动作由人工触发）
