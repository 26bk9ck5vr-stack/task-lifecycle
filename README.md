# Task Lifecycle

GSD-style 任务生命周期管理框架 — Hermes Agent 专用。

## 概述

Task Lifecycle 将一个任务从想法到交付切分为 5 个阶段，每个阶段有明确的产出和验收条件：

```
Discuss → Plan → Execute → Verify → Ship
```

- **Discuss**：执行前对齐目标/约束/风险
- **Plan**：SP 出初稿 → CC 优化 → Gemini 最终
- **Execute**：Kanban 建任务 → delegate_task 派发 → checkpoint 记录
- **Verify**：CC 验证产出质量和完整性
- **Ship**：归档 + 汇报用户

## 核心能力

### 1. 专属 Agent 池

内置 6 种 GSD 风格专业 subagent skill（位于 `gsd-adapted/`）：

| Agent | 文件 | 用途 |
|-------|------|------|
| researcher | gsd-researcher.md | 调研/查资料 |
| planner | gsd-planner.md | 任务分解/规划 |
| executor | gsd-executor.md | 执行代码任务 |
| verifier | gsd-verifier.md | 验证产出质量 |
| code-reviewer | gsd-code-reviewer.md | 代码审查 |
| debugger | gsd-debugger.md | 诊断问题 |

加载方式（在 delegate_task 的 context 中指定）：
```
skill_view(name='task-lifecycle/gsd-executor')
```

### 2. Commit 原子性（Worktree 模式）

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
├── gsd-adapted/                 # Hermes 专用 agent skills（推荐使用）
│   ├── gsd-researcher.md
│   ├── gsd-planner.md
│   ├── gsd-executor.md
│   ├── gsd-verifier.md
│   ├── gsd-code-reviewer.md
│   └── gsd-debugger.md
├── agents/                       # 原始 GSD agent 文件（参考）
│   ├── gsd-executor.md
│   ├── gsd-debugger.md
│   └── ...（共7个）
├── scripts/
│   ├── kanban_checkpoint.py      # worktree-aware checkpoint
│   └── recovery_exec.py          # worktree rollback/abort
└── references/
    └── deviation_rules.md         # GSD 执行规则（Rule 1-4）
```

## 使用前提

- Hermes Agent（安装了 task-lifecycle skill）
- Kanban DB（`~/.hermes/kanban.db`）
- Git 仓库
- CC（Claude Code）或星火作为 LLM backend

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

### 2. 执行 Plan

用 dual-agent-loop 或直接写 plan.md，将任务分解为 Kanban 子任务。

### 3. Execute with Checkpoint

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

### 4. Recovery

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

## 验证结果（自测）

| 组件 | 验证点 | 结果 |
|------|--------|------|
| discuss | discuss.md 格式完整 | ✅ |
| gsd-adapted agents | 7个文件内容正确 | ✅ |
| worktree checkpoint | schema_version=2，commit SHA 正确写入 | ✅ |
| worktree rollback | git checkout 回滚成功 | ✅ |
| Kanban 流转 | create→execute→done 正常 | ✅ |

## 与 GSD 的关系

Task Lifecycle 移植自 [get-shit-done](https://github.com/gsd-build/get-shit-done)（63k stars），针对 Hermes Agent 环境做了适配：

- GSD 的 6-command loop → Hermes 的 5-phase lifecycle
- GSD 的 32 种专用 agent → 本项目的 6 种核心 agent
- GSD 的本地执行 → Hermes 的 Kanban + worktree 隔离
- GSD 的 atomic commit → Hermes 的 per-task worktree

原始 GSD agent 文件保存在 `agents/` 目录供参考。

## License

MIT
