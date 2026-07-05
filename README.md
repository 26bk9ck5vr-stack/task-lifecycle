# Task Lifecycle

GSD-style 任务生命周期管理框架 — Hermes Agent 专用。

## 概述

Task Lifecycle 将一个任务从想法到交付切分为 5 个阶段，每个阶段有明确的产出和验收条件：

```
Discuss → Plan → Execute → Verify → Ship
```

- **Discuss**：执行前对齐目标/约束/风险
- **Plan**：MOA 3路并行出方案（S1 + S2 + S3（3路reference）→ Aggregator）
- **Execute**：Kanban 建任务 → delegate_task 派发 → checkpoint 记录
- **Verify**：MOA 3视角验证（Completeness / CodeQuality / DataFlow → Aggregator）
- **Ship**：归档 + 汇报用户

## 核心能力

### 1. MOA 驱动 Plan & Verify

Phase 1 和 Phase 3 由 MOA（Mixture of Agents）驱动，3 个 reference model 并行工作，aggregator 综合输出：

**Plan MOA**：结构化分解 × 代码实现路径 × 架构风险 → plan.md
**Verify MOA**：完整性审查 × 代码质量审查 × 数据流追踪 → VERIFICATION.md

### 2. 专属 Agent 池

内置 GSD 风格专业 subagent skill（位于 `gsd-adapted/`）：

| Agent | 文件 | 用途 |
|-------|------|------|
| researcher | gsd-researcher.md | 调研/查资料 |
| planner | gsd-planner.md | 单agent规划（备用） |
| executor | gsd-executor.md | 执行代码任务 |
| verifier | gsd-verifier.md | 单agent验证（备用） |
| moa | **gsd-moa.md** | 统一MOA skill（Phase 1 + Phase 3） |
| code-reviewer | gsd-code-reviewer.md | 代码审查 |
| debugger | gsd-debugger.md | 调试 |

加载方式（在 delegate_task 的 context 中指定）：
```
skill_view(name='task-lifecycle/gsd-moa')
skill_view(name='task-lifecycle/gsd-executor')
```

### 3. Commit 原子性（Worktree 模式）

每个子任务在独立的 git worktree 中执行，失败时只回滚当前 worktree，不影响主分支。

**流程**：
```
Task开始 → 创建worktree+新分支 → worktree内执行 → 提交commit
    ↓ 成功 → merge到主分支
    ↓ 失败 → git checkout {commit} 回滚worktree → 重新派发
```

**配套脚本**（位于 `scripts/`）：
- `kanban_checkpoint.py`：worktree-aware，schema_version=2
- `recovery_exec.py`：支持 worktree rollback / abort 清理

## 目录结构

```
task-lifecycle/
├── SKILL.md                      # 主 skill 文档
├── README.md                     # 本文件
├── gsd-adapted/                 # Hermes 专用 agent skills
│   ├── gsd-researcher.md
│   ├── gsd-researcher-domain.md
│   ├── gsd-planner.md           # 单agent planner（备用）
│   ├── gsd-executor.md
│   ├── gsd-verifier.md          # 单agent verifier（备用）
│   ├── gsd-moa.md               # 统一MOA skill（Phase 1 Plan + Phase 3 Verify）
│   ├── gsd-code-reviewer.md
│   └── gsd-debugger.md
├── agents/                      # 原始 GSD agent 文件（参考）
│   └── ...（共7个）
├── scripts/
│   ├── kanban_checkpoint.py     # worktree-aware checkpoint
│   └── recovery_exec.py         # worktree rollback/abort
└── references/
    └── deviation_rules.md       # GSD 执行规则（Rule 1-4）
```

## 使用前提

- Hermes Agent（安装了 task-lifecycle skill）
- Kanban DB（`~/.hermes/kanban.db`）
- Git 仓库

## 快速开始

### 1. 创建 Discuss

在 `~/.hermes/task-lifecycle/{task_id}/discuss.md` 写入：

```markdown
## Discuss — {task_id}

### 目标
要交付什么、验收标准是什么

### 约束
技术限制、时间、资源、不能碰的边界

### 已知风险
最可能失败的点

### 对齐确认
- [ ] 目标理解一致
- [ ] 约束条件可行
- [ ] 风险已被 Plan 覆盖
```

### 2. Phase 1 — MOA Plan

使用 `gsd-moa` skill Part A，3 路 reference model 并行出方案：

```python
skill_view(name='task-lifecycle/gsd-moa')
from agent.moa_loop import aggregate_moa_context

out = aggregate_moa_context(
    user_prompt=plan_prompt,
    api_messages=[{"role":"user","content": discuss_content}],
    reference_models=[
        {"provider": "a3b", "model": "S1_MODEL"},       # S1: 结构化分解
        {"provider": "minimax-cn", "model": "S2_MODEL"},  # S2: 代码实现路径
        {"provider": "a3b", "model": "S3_MODEL"},    # S3: 架构风险
    ],
    aggregator={"provider": "a3b", "model": "S3_MODEL"},
)
```

产出：`~/.hermes/task-lifecycle/{task_id}/plan.md`

### 3. Phase 2 — Execute

分解 plan.md 为 Kanban 子任务，delegate_task 并行执行，checkpoint 记录：

```bash
python scripts/kanban_checkpoint.py \
  --task-id <id> --stage <stage> \
  --artifacts /path/to/file.md \
  --next-step next_stage \
  --summary "完成了什么" \
  --worktree /tmp/worktrees/<id> \
  --branch task-<id> --git-repo ~/.hermes \
  --create-worktree
```

### 4. Phase 3 — MOA Verify

使用 `gsd-moa` skill Part B，3 个 verifier 并行审查：

```python
skill_view(name='task-lifecycle/gsd-moa')
from agent.moa_loop import aggregate_moa_context

out = aggregate_moa_context(
    user_prompt=verifier_prompt,
    api_messages=[{"role":"user","content": plan_and_summary}],
    reference_models=[
        {"provider": "a3b", "model": "S1_MODEL"},       # V1: Completeness
        {"provider": "minimax-cn", "model": "S2_MODEL"},  # V2: CodeQuality
        {"provider": "a3b", "model": "S3_MODEL"},    # V3: DataFlow
    ],
    aggregator={"provider": "a3b", "model": "S3_MODEL"},
)
```

产出：`~/.hermes/task-lifecycle/{task_id}/VERIFICATION.md`

### 5. Recovery

```bash
python scripts/recovery_exec.py --task-id <id> --action rollback
# action: resume | rollback | abort
```

## Deviation Rules

执行中自动处理偏差，**不打断流程**：

| Rule | 触发条件 | 处理方式 |
|------|---------|---------|
| Rule 1 | 代码不工作（错误/崩溃） | 修 → 验证 → 继续 |
| Rule 2 | 缺少必要性功能 | 补 → 验证 → 继续 |
| Rule 3 | blocking 问题（类型错误/导入失败） | 修 → 继续 |
| Rule 4 | 架构级变更 | STOP → 用户决策 |

## 与 GSD 的关系

Task Lifecycle 移植自 [get-shit-done](https://github.com/gsd-build/get-shit-done)（63k stars），针对 Hermes Agent 环境做了适配：

- GSD 的 6-command loop → Hermes 的 5-phase lifecycle
- GSD 的 32 种专用 agent → 本项目的 6 种核心 agent + 1 个 MOA skill
- GSD 的本地执行 → Hermes 的 Kanban + worktree 隔离
- GSD 的 atomic commit → Hermes 的 per-task worktree

原始 GSD agent 文件保存在 `agents/` 目录供参考。

## License

MIT
