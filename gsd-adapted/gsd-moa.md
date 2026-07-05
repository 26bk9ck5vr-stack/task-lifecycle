---
name: gsd-moa
description: Unified MOA skill for task-lifecycle — covers Phase 1 Plan and Phase 3 Verify. 3 reference models run in parallel, aggregator synthesizes output.
category: agent
---

# Role

统一 MOA Skill，覆盖 Phase 1 Plan 和 Phase 3 Verify 两个阶段。

**MOA 配置**（固定）：
```
S1: 第1个reference模型 — 擅长结构化分解、任务切片
S2: 第2个reference模型 — 擅长代码实现路径、依赖分析
S3: 第3个reference模型 — 擅长架构设计、风险预判
Aggregator: 综合能力最强的模型
```

**调用方式**：
```python
from agent.moa_loop import aggregate_moa_context

out = aggregate_moa_context(
    user_prompt="...",
    api_messages=[{"role":"user","content":"..."}],
    reference_models=[
        {"provider": "a3b", "model": "S1_MODEL"},       # S1
        {"provider": "minimax-cn", "model": "S2_MODEL"},  # S2
        {"provider": "a3b", "model": "S3_MODEL"},    # S3
    ],
    aggregator={"provider": "a3b", "model": "AGGREGATOR_MODEL"},
)
```

---

# Part A — MOA Planner（Phase 1）

## 用途

接收 `discuss.md`，3 路 reference model 并行出方案，aggregator 综合成 `plan.md`。

**替换**：`obra-writing-plans`（SP→CC→Gemini 三步链）

## 输入

`~/.hermes/task-lifecycle/{task_id}/discuss.md`（目标/约束/风险）

## 执行流程

### 步骤 1：读取 discuss.md

提取：
- 目标（goal）
- 约束（constraints）
- 已知风险（risks）
- 完成标准（acceptance criteria）

### 步骤 2：构建 reference prompt

```python
role_descriptions = {
    "S1": "第1个reference模型 — 擅长结构化分解、任务切片、P0 优先级排序",
    "S2": "第2个reference模型 — 擅长代码实现路径分析、依赖关系、技术选型",
    "S3": "第3个reference模型 — 擅长架构设计、长期风险预判、系统性思维"
}

prompt = f"""你是 MOA Planner 的 {role}。

**Discuss 内容**：
目标：{goal}
约束：{constraints}
风险：{risks}

**你的专长**：{role_description}
**你的角度**：{what_you_focus_on}

**输出要求**（中文，≤400字）：
1. **TL;DR**：一句话总结方案
2. **P0 任务清单**（最多5项，按执行顺序）
3. **技术决策**（关键选型，1-3条，给出理由）
4. **风险点**（对应 discuss 里的已知风险，你的对策）
5. **验收标准**（可测试的条目）

**格式**：纯文本，条理清晰，不用 Markdown 表格。
"""
```

### 步骤 3：Aggregator prompt

```
## 你的任务

你是一个方案综合专家。3 个不同专长的 AI 同时给出了 {feature_name} 实现方案。

**方案A（第1个reference模型，结构化分解专家）**：
{方案A内容}

**方案B（第2个reference模型，代码实现路径专家）**：
{方案B内容}

**方案C（第3个reference模型，架构风险专家）**：
{方案C内容}

**请综合 3 份方案，输出最终 plan.md**：
- 选取每个方案最合理的部分合并
- 解决冲突（取最稳妥的方案）
- 风险部分必须包含所有 3 个方案提到的风险
- P0 任务控制在 5 项以内

**输出格式**：Markdown
**语言**：中文
**字数**：≤800字
```

### 步骤 4：写入 plan.md

```python
write_file(
    path=f"~/.hermes/task-lifecycle/{task_id}/plan.md",
    content=aggregator_output
)
```

## 错误处理

- 任意 reference 超时/失败 → 用剩余的 2 个重新综合，注明降级模式
- 只剩 1 个 → 返回该方案，注明"降级：单 reference"
- Aggregator 失败 → 返回 3 个方案并列，让主 agent 人工选择

---

# Part B — MOA Verifier（Phase 3）

## 用途

3 个 reference verifier 从不同角度并行审查已完成的任务，aggregator 综合成 `VERIFICATION.md`。

**替换**：`obra-verification-before-completion`（单 agent 验证）

## 输入

- `~/.hermes/task-lifecycle/{task_id}/plan.md`（原始方案）
- `~/.hermes/task-lifecycle/{task_id}/SUMMARY.md`（执行结果）
- 项目源码（关键文件内容 inline 到 prompt）

## 3 个 Verifier 的分工

| Verifier | 模型 | 角度 | 验证内容 |
|----------|------|------|----------|
| V1 | 第1个reference模型 | Completeness（完整性） | must_haves对照、scope边界、所有P0任务是否完成 |
| V2 | 第2个reference模型 | CodeQuality（代码质量） | 反模式、存根、债务标记、空实现、硬编码 |
| V3 | 第3个reference模型 | DataFlow（数据流） | API→DB连接、Props传递、数据源真实性 |

## Reference prompt（3路并行）

```python
verifier_prompts = {
    "V1": """你是 Verifier-Completeness。

**任务**：验证 {task_name} 的实现是否完整。

**plan.md P0 任务**：
{p0_tasks}

**请检查**：
1. 所有 P0 任务是否完成
2. success_criteria 是否满足
3. 是否有遗漏的功能点
4. Out of Scope 是否被遵守

**输出格式**（JSON，中文）：
{{
  "perspective": "Completeness",
  "rating": "PASS / PARTIAL / FAIL",
  "completed": ["任务1", "任务2"],
  "incomplete": ["任务3（缺少X）"],
  "out_of_scope_violations": [],
  "gaps": ["gap1", "gap2"]
}}
""",

    "V2": """你是 Verifier-CodeQuality。

**任务**：验证 {task_name} 的代码质量。

**修改的源文件**：
{file_list}

**请扫描**：
- TBD/FIXME/XXX 债务标记
- 空实现（return null/{}）
- console.log-only 实现
- 硬编码空数据
- 模块化/错误处理/输入校验问题

**输出格式**（JSON，中文）：
{{
  "perspective": "CodeQuality",
  "rating": "PASS / WARNING / CRITICAL",
  "issues": [
    {{"file": "path", "line": n, "type": "FIXME/stub/etc", "severity": "高/中/低", "description": "..."}}
  ],
  "gaps": ["gap1"]
}}
""",

    "V3": """你是 Verifier-DataFlow。

**任务**：追踪 {task_name} 的数据流。

**关键组件/页面**：
{components}

**请验证**：
1. 组件是否连接了真实数据源（不是硬编码空值）
2. API 调用是否有响应处理
3. Props 传递是否真实（非空值）
4. 数据库查询是否返回真实数据

**输出格式**（JSON，中文）：
{{
  "perspective": "DataFlow",
  "rating": "PASS / DISCONNECTED / HOLLOW",
  "flowing": ["API → 组件（真实数据）"],
  "disconnected": ["组件X — 原因"],
  "hollow": ["组件Y — 上游空值"],
  "gaps": ["gap1"]
}}
"""
}
```

## Aggregator prompt

```
## 你的任务

你是验证结果综合专家。3 个不同视角的 verifier 对 {task_id} 完成了审查。

**视角1 — Completeness**：
{V1 JSON}

**视角2 — CodeQuality**：
{V2 JSON}

**视角3 — DataFlow**：
{V3 JSON}

**请综合 3 份报告，输出最终 VERIFICATION.md**：
- Overall rating 取最严重者（任意视角 FAIL → 整体 FAIL）
- gaps 包含所有 3 个视角提出的 gaps，去重
- 每个 gap 必须有修复建议
- Decision：CAN SHIP / NEEDS FIX / REDO PLAN

**输出格式**：Markdown
**语言**：中文
**字数**：≤600字
```

## 输出格式（VERIFICATION.md）

```markdown
---
phase: 3
task_id: {task_id}
date: {ISO date}
verifier: MOA (V1=第1ref模型, V2=第2ref模型, V3=第3ref模型, Aggregator=聚合模型)
---

# Verification Report — {task_id}

## Overall Rating
**{OVERALL}** — {一句话总结}

## Summary
| 视角 | 评级 | 关键发现 |
|------|------|----------|
| Completeness | PASS/PARTIAL/FAIL | {一句话} |
| CodeQuality | PASS/WARNING/CRITICAL | {N个问题} |
| DataFlow | PASS/DISCONNECTED/HOLLOW | {N个问题} |

## Completeness
### 通过项
- [x] {任务}

### 未完成项
- [ ] {任务} — {缺少什么}

## Code Quality
### 通过项
- [x] {文件} — {描述}

### 问题列表
| 文件 | 行 | 类型 | 严重度 | 描述 |
|------|----|------|--------|------|
| {file} | {n} | {type} | {severity} | {desc} |

## Data Flow
### 正常
- ✅ {组件} — {描述}

### 断连
- ❌ {组件} — {原因}

### Hollow
- ⚠️ {组件} — {原因}

## Gaps
1. **{gap1}** — 文件:{file} — 修复建议:{suggestion}

## Decision
- [ ] **CAN SHIP** — 无阻塞问题
- [ ] **NEEDS FIX** — 修复 gaps 后可 ship
- [ ] **REDO PLAN** — 方向性问题，需打回 Phase 1

---
*Generated: {timestamp} | MOA: 3-verifier parallel → aggregation*
```

## 错误处理

- 任意 reference 超时/失败 → 用剩余的继续，注明降级
- Aggregator 失败 → 返回 3 份报告并列 + 主 agent 人工判定
- 所有都失败 → 输出错误报告，请求人工介入

---

# 使用场景

| 场景 | 使用 Part |
|------|-----------|
| task-lifecycle Phase 1 | Part A — MOA Planner |
| task-lifecycle Phase 3 | Part B — MOA Verifier |
| discuss.md 已有，需要多视角出方案 | Part A |
| 所有子任务 done，需要验收 | Part B |

# 不适用

- discuss.md 不完整（先补 discuss）
- 子任务未全部完成（等待 Execute 完成）
- 简单任务（单 agent 足够，不值得 MOA 成本）
