---
name: task-lifecycle
description: "基于 Superpowers 的任务生命周期管理 — Discuss → Plan → Execute → Verify → Ship，完整闭环"
---

# Task Lifecycle — 基于 Superpowers 的任务闭环

> 基于 obra/superpowers 系列技能的任务生命周期管理框架。

## 定位

**这不是新系统**，是 superpowers 系列技能的整合封装。

- 使用 `writing-plans` 负责：任务规划
- 使用 `executing-plans` 负责：执行监控、checkpoint
- 使用 `verification-before-completion` 负责：验证产出
- 使用 `dispatching-parallel-agents` 负责：并行子任务调度
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
│  Phase 1: Plan（复用 writing-plans skill）                  │
│  使用 writing-plans 技能创建详细计划                         │
│  产出：plan.md                                              │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Phase 2: Execute（复用 executing-plans + dispatching）     │
│  Kanban 建主任务 + N 个子任务                                │
│  使用 dispatching-parallel-agents 派发子任务                 │
│  每个子任务 spawn subagent 执行                              │
│  完成 → kanban_checkpoint() → stale_monitor 监控           │
│  偏差自动处理（Deviation Rules）                             │
│  产出：各子任务 artifacts + SUMMARY.md                      │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Phase 3: Verify（复用 verification-before-completion）     │
│  使用 verification-before-completion 验证产出质量            │
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

## Phase 1 — Plan（MOA 驱动）

使用 `gsd-moa` skill Part A，3 路 reference model 并行出方案，aggregator 综合成 plan.md：

```python
skill_view(name='task-lifecycle/gsd-moa')

# Part A: MOA Planner（Phase 1）
from agent.moa_loop import aggregate_moa_context

out = aggregate_moa_context(
    user_prompt=plan_prompt,
    api_messages=[{"role":"user","content": discuss_content}],
    reference_models=[
        {"provider": "a3b", "model": "xopqwen36v35b"},       # S1: 千问35b
        {"provider": "minimax-cn", "model": "MiniMax-M2.7"},  # S2: MiniMax
        {"provider": "a3b", "model": "xopqwen36397b17b"},    # S3: 千问397b
    ],
    aggregator={"provider": "a3b", "model": "xopqwen36397b17b"},
)
write_file(path=f"~/.hermes/task-lifecycle/{task_id}/plan.md", content=out)
```

**MOA 配置**：
- S1=千问35b（结构化分解）
- S2=MiniMax-M2.7（代码实现路径）
- S3=千问397b（架构风险）
- Aggregator=千问397b（综合）

**输出**：
- `~/.hermes/task-lifecycle/{task_id}/plan.md` — MOA 综合方案

**不再使用**：SP→CC→Gemini 三步链

### Plan 的两种模式（用户偏好：初稿分离）

按用户的工作流偏好，**Plan 阶段可以拆成"先写初稿不实装"和"实装"两个子阶段**，避免一上来就改生产代码：

| 模式 | 用途 | 产出 | 进入下一阶段的条件 |
|------|------|------|-------------------|
| **Plan: Draft（初稿）** | 综合需求 + 设计文档 + 风险清单 + 验收标准；**不写代码、不跑命令** | `INITIAL_DRAFT.md` 或 `discuss.md` | 用户显式回复"开干 / 实装" |
| **Plan: Concrete（实装）** | 切到 P0 任务清单 + 代码模板 + 命令清单 | `plan.md` | 用户 review 通过 |

**典型用法**（用户说"先写初稿（不实装）"时）：
1. 收集所有相关材料（设计文档、其他项目 README、官方 docs）
2. 综合出**单一文档**（不是多个 plan.md 切片），包含：
   - TL;DR（一句话总结）
   - 范围（In/Out）—— 用户最在意**不做清单**
   - 第一刀切哪里（P0 任务 + 验收标准）
   - 技术决策（钉死版，不留模糊）
   - 端点 / CLI / schema 清单
   - 6 个待用户决策的开放问题
3. 写出后等用户 review，**绝对不要自动进入 Phase 2**

**为什么重要**：memos-graph、MemOS 插件迁移这类"已有方案 + 想综合出新方案"的任务，初稿不需要实装就能让用户判断方向对不对。Phase 2 一启动就回滚成本高（DB schema 已建、文件已写）。

### 与 DESIGN.md 的关系

- **DESIGN.md**：完整设计文档（30+ 页）——讲"是什么、为什么"——只写一次，长期参考
- **INITIAL_DRAFT.md**：**初稿 / 开题文档**（10-15 节）——讲"第一刀切哪、什么时候算做完、什么不做"——review 时改这个
- **plan.md**：实装计划——review 通过后再写

**经验法则**：用户说"先写初稿"或"不实装" → INITIAL_DRAFT.md 路径；说"开干"或"实装" → plan.md 路径。两个文件不要混。

## Phase 2 — Execute（复用 executing-plans + dispatching-parallel-agents）

### 入口

Plan 完成后，使用 `dispatching-parallel-agents` 分解 plan.md 为 N 个子任务，写入 Kanban：

```python
# 加载技能
skill_view(name='obra-dispatching-parallel-agents')
skill_view(name='task-lifecycle')  # 加载 task-lifecycle 获取子任务配置

# 使用 dispatching-parallel-agents 的方法派发任务
from delegate_task import delegate_task

# 分解计划为子任务
subtasks = delegate_task(
  goal="分解计划为可执行的子任务",
  context=plan.md 内容，
  toolsets=["terminal", "file"]
)

# 创建 Kanban 任务
for subtask in subtasks:
    terminal(command="hermes kanban create \"{subtask[\"description\"]}\" --parent {parent_id}")
```

### 子任务执行（自动使用 A3B 模型）

**使用 task-lifecycle 提供的执行器**，自动注入 A3B 模型配置：

```python
# 加载 task-lifecycle 执行器
exec(open("~/.hermes/skills/task-lifecycle/scripts/execute_subtask.py").read())

# 执行子任务（自动使用 A3B 模型）
result = execute_subtask(
  goal="执行子任务：{description}",
  context={plan.md 内容 + discuss.md 内容},
  toolsets=["terminal", "file", "web"]
)
```

或者直接在 `delegate_task` 中指定（不推荐，容易忘记）：

```python
delegate_task(
  goal="执行子任务：{description}",
  context={plan.md 内容 + discuss.md 内容 + artifacts 路径},
  toolsets=["terminal", "file", "web"],
  model="astron-code-latest",  # A3B 模型
  provider="custom"
)
```

### 子任务模型配置（A3B）

task-lifecycle 的子任务执行**内置**以下模型配置，无需每次临时指定：

| 配置项 | 值 |
|--------|-----|
| Provider | `custom` |
| Model | `astron-code-latest` |
| Base URL | `https://maas-coding-api.cn-huabei-1.xf-yun.com/v2` |

**API Key 配置**（一次性）：
在 `~/.hermes/.env` 中添加：
```
CUSTOM_API_KEY=ef1f32...之后所有 task-lifecycle 派发的子任务都会自动使用 A3B 配置，无需重复指定。

**重要原则**：
- **主模型和子任务模型分离**：主模型用于规划、验证等核心决策，子任务模型用于执行具体任务
- **不要混用**：主模型配置修改不影响子任务的 A3B 配置
- **配置持久化**：将 A3B 的 API key 写入 `~/.hermes/.env`，避免每次会话重新配置

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

## Phase 3 — Verify（MOA 3视角驱动）

使用 `gsd-moa` skill Part B，3 个 reference verifier 并行审查，aggregator 综合成 VERIFICATION.md：

```python
skill_view(name='task-lifecycle/gsd-moa')

# Part B: MOA Verifier（Phase 3）
from agent.moa_loop import aggregate_moa_context

out = aggregate_moa_context(
    user_prompt=verifier_prompt,
    api_messages=[{"role":"user","content": f"plan={plan_content}\nsummary={summary_content}"}],
    reference_models=[
        {"provider": "a3b", "model": "xopqwen36v35b"},       # V1: Completeness
        {"provider": "minimax-cn", "model": "MiniMax-M2.7"},  # V2: CodeQuality
        {"provider": "a3b", "model": "xopqwen36397b17b"},    # V3: DataFlow
    ],
    aggregator={"provider": "a3b", "model": "xopqwen36397b17b"},
)
write_file(path=f"~/.hermes/task-lifecycle/{task_id}/VERIFICATION.md", content=out)
```

**3 视角分工**：
- V1（千问35b）：Completeness — must_haves 对照、scope 边界
- V2（MiniMax-M2.7）：CodeQuality — 反模式、存根、债务标记
- V3（千问397b）：DataFlow — 数据流追踪、API→DB 连接

**MOA 输出**：
- `~/.hermes/task-lifecycle/{task_id}/VERIFICATION.md`

**Decision 结论**：
- `CAN SHIP`：无阻塞问题
- `NEEDS FIX`：修复 gaps 后可 ship
- `REDO PLAN`：方向性问题，打回 Phase 1

**不再使用**：单 agent verification

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
│   ├── verify_result.md       # Phase 3 产出
│   └── SUMMARY.md             # Phase 2 产出
├── gsd-adapted/               # 适配后的 Hermes 专用 agent skill
│   ├── gsd-researcher.md
│   ├── gsd-researcher-domain.md
│   ├── gsd-planner.md
│   ├── gsd-executor.md
│   ├── gsd-verifier.md         # 单 agent verifier（备用）
│   ├── gsd-moa.md             # 统一 MOA skill（Phase 1 Plan + Phase 3 Verify）
│   ├── gsd-code-reviewer.md
│   └── gsd-debugger.md
├── scripts/                   # worktree-aware 版本的 checkpoint/recovery
│   ├── kanban_checkpoint.py   # schema_version=2，支持 worktree
│   ├── recovery_exec.py       # 支持 worktree rollback/abort
│   └── execute_subtask.py     # 子任务执行器，自动使用 A3B 模型
└── references/
    └── deviation_rules.md     # 从 GSD executor 移植
```

## ⚠️ Pitfalls（执行陷阱）

### Phase 1: 星火 subagent 需要 retry 机制

星火引擎对 task-lifecycle 的调用会因为并发限流报 `code: 10010, RecvFromEngineError:Engine Busy`。

**workaround**：不要用 `delegate_task` 调用星火做 task-lifecycle planning。直接用 terminal + write_file 写 plan，或者用其他模型做 planning。

### Phase 2: subagent 执行慢是正常的，等着

subagent 执行复杂任务时可能需要较长时间，不要因为等待了就放弃。给 subagent 更长的 timeout 让它跑完。

### Phase 3: gsd-adapted agents 需验证后才能用于生产

gsd-adapted agents 当前存在明确的工具映射错误，必须经过 review 才能实际使用：

**已知问题**：
- `gsd-executor.md`（6/10）：第 48 行混用 `grep -n`（bash 命令），但 `terminal` 工具列表中没有 grep；正确的应该用 `search_files`
- `gsd-debugger.md`（6/10）：tools 太少，缺 git/grep；`<trigger>` 引用无定义

**验证方法**：
```bash
cd /home/gato/.hermes && echo "评估 ~/.hermes/task-lifecycle/gsd-adapted/gsd-executor.md：role 是否清晰、tools 映射是否合理、是否有明显错误。评分 1-10。" | hermes chat -q --dangerously-skip-permissions
```

**原则**：gsd-adapted agents 是参考材料，生产使用前必须 review，修复发现的问题。

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
`hermes` 命令可能不在系统 PATH，调用时用完整路径或确保 PATH 已配置。

其他限制：
- `resume` 依赖 worker 是否还持有任务
- `abort` 后无法反悔
- Discuss 阶段的对齐确认是口头承诺，无强制执行机制

## 验证记录

**验证目标**：task-lifecycle 全流程 + 基于 superpowers 的工作流

**验证方法**：self-verification（实际跑 task-lifecycle 框架）

**验证结果**：

| 组件 | 验证点 | 结果 |
|------|--------|------|
| discuss | discuss.md 包含 目标/约束/风险/完成标准 | ✅ |
| gsd-adapted agents | 7 个文件，内容正确可读 | ✅ |
| worktree checkpoint | schema_version=2，commit SHA 正确写入 | ✅ |
| worktree rollback | git checkout 回滚成功，文件被删除 | ✅ |
| Kanban 任务流转 | create→execute→done 正常 | ✅ |

**验证陷阱**：
- 星火引擎：Engine Busy (10010) 错误频繁，建议用 terminal 直接验证
- subagent 执行：可能需要较长时间，建议设置合理的 timeout

**已知问题**：
- `gsd-executor.md`：**6/10** — tools 混用 `grep -n`，第 48 行需改用 `search_files`
- `gsd-debugger.md`：**6/10** — tools 太少（缺 git/grep），`<trigger>` 引用无定义

---

## 不做的事

- 不改 Hermes 核心
- 不做自动 recovery（所有动作由人工触发）
- 不强制依赖特定模型（CC/Gemini 等）

---

## 相关参考

- **从 GitHub 手动安装技能**：`references/github-skill-installation.md` — 当 `hermes skills install` 失败时的手动安装流程
- **Deviation Rules**：`references/deviation_rules.md` — GSD 执行规则详情
