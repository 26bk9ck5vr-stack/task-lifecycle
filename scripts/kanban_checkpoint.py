#!/usr/bin/env python3
"""
kanban_checkpoint.py — 子任务完成后调用，写入 checkpoint 到 Kanban tasks 表。

Worktree-aware 版本：支持 per-task git worktree 隔离。

新增参数：
    --worktree     worktree 目录路径（如 /tmp/hermes-worktrees/{task_id}）
    --branch       worktree 对应的分支名（如 task-{task_id}）
    --git-repo     git 仓库路径（默认 ~/.hermes）
    --create-worktree  传入此标志则创建 worktree（task 开始时用）

用法：
    # Task 开始：创建 worktree + 写初始 checkpoint
    python kanban_checkpoint.py --task-id <id> --stage start \
        --worktree /tmp/hermes-worktrees/<id> --branch task-<id> \
        --git-repo ~/.hermes --create-worktree \
        --artifacts "" --next-step execute --summary "Task started, worktree ready"

    # Subtask 完成：记录 commit SHA + 更新 artifacts
    python kanban_checkpoint.py --task-id <id> --stage <stage> \
        --artifacts /path/to/file1.md,/path/to/file2.md \
        --next-step next_stage --summary "Completed X"

环境变量：
    HERMES_KANBAN_DB   Kanban db 路径，默认 ~/.hermes/kanban.db
"""

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


KANA_BAN_DB = Path.home() / ".hermes" / "kanban.db"


def _add_checkpoint_columns():
    """幂等添加 checkpoint 相关列。如果列已存在则静默跳过。"""
    conn = sqlite3.connect(KANA_BAN_DB)
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN stage TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN checkpoint_data TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN last_checkpoint_at INTEGER")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise
    try:
        conn.execute(
            "ALTER TABLE tasks ADD COLUMN checkpoint_status TEXT DEFAULT 'active'"
        )
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise
    conn.close()


def _get_current_commit(repo_path: str) -> str | None:
    """获取当前 HEAD commit SHA（前8位）。"""
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _create_worktree(worktree_path: str, branch: str, repo_path: str) -> tuple[bool, str]:
    """创建 worktree 分支。返回 (成功, 错误信息)。"""
    try:
        # 先创建目录
        Path(worktree_path).mkdir(parents=True, exist_ok=True)
        # 创建 worktree + 新分支
        result = subprocess.run(
            ["git", "-C", repo_path, "worktree", "add",
             worktree_path, "-b", branch],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            return True, ""
        else:
            # 如果分支已存在，尝试直接添加 worktree
            if "分支已存在" in result.stderr or "branch already exists" in result.stderr.lower():
                result = subprocess.run(
                    ["git", "-C", repo_path, "worktree", "add",
                     worktree_path, branch],
                    capture_output=True, text=True, timeout=60
                )
                if result.returncode == 0:
                    return True, ""
            return False, result.stderr.strip()
    except Exception as e:
        return False, str(e)


def kanban_checkpoint(
    task_id: str,
    stage: str,
    artifacts: list[str],
    next_step: str,
    summary: str,
    worktree: str | None = None,
    branch: str | None = None,
    git_repo: str | None = None,
    create_worktree: bool = False,
) -> bool:
    """
    写入 checkpoint。

    Args:
        task_id: Kanban 任务 ID
        stage: 当前 stage 名称（如 "start", "subtask_A", "done"）
        artifacts: 产出文件路径列表
        next_step: 下一步是什么
        summary: 本次 stage 简要描述
        worktree: worktree 目录路径（可选）
        branch: worktree 对应的分支名（可选）
        git_repo: git 仓库路径（可选，默认 ~/.hermes）
        create_worktree: 是否创建 worktree（task 开始时用）
    """
    repo_path = git_repo or str(Path.home() / ".hermes")

    # 获取当前 commit：在 worktree 内执行时读 worktree 的 HEAD
    current_commit = _get_current_commit(worktree if worktree else repo_path)

    checkpoint_data = {
        "schema_version": 2,  # 版本2：支持 worktree
        "artifacts": artifacts,
        "next_step": next_step,
        "summary": summary,
        "worktree": worktree,
        "branch": branch,
        "git_repo": repo_path,
        "commit": current_commit,
    }

    # 如果需要创建 worktree
    if create_worktree and worktree and branch:
        ok, err = _create_worktree(worktree, branch, repo_path)
        if not ok:
            print(f"[WARN] worktree creation failed: {err}", file=sys.stderr)
            # 不阻塞 checkpoint，继续写入

    try:
        _add_checkpoint_columns()
        conn = sqlite3.connect(KANA_BAN_DB)
        now = time.time()
        cur = conn.execute(
            """
            UPDATE tasks SET
                stage = ?,
                checkpoint_data = ?,
                last_checkpoint_at = ?,
                checkpoint_status = 'active'
            WHERE id = ?
            """,
            (stage, json.dumps(checkpoint_data), now, task_id),
        )
        conn.commit()
        affected = cur.rowcount
        conn.close()
        if affected == 0:
            print(f"[ERROR] task not found: {task_id}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"[ERROR] kanban_checkpoint failed: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="写入 checkpoint 到 Kanban（worktree-aware）")
    parser.add_argument("--task-id", required=True, help="Kanban 任务 ID")
    parser.add_argument("--stage", required=True, help="当前 stage 名称")
    parser.add_argument(
        "--artifacts",
        required=True,
        help="逗号分隔的产出文件路径，空则传空字符串",
    )
    parser.add_argument("--next-step", required=True, help="下一步是什么")
    parser.add_argument("--summary", required=True, help="本次 stage 简要描述")
    parser.add_argument("--worktree", help="worktree 目录路径")
    parser.add_argument("--branch", help="worktree 对应的分支名")
    parser.add_argument("--git-repo", default=str(Path.home() / ".hermes"),
                        help="git 仓库路径")
    parser.add_argument("--create-worktree", action="store_true",
                        help="创建 worktree（task 开始时用）")
    args = parser.parse_args()

    artifacts = [a.strip() for a in args.artifacts.split(",") if a.strip()]

    success = kanban_checkpoint(
        task_id=args.task_id,
        stage=args.stage,
        artifacts=artifacts,
        next_step=args.next_step,
        summary=args.summary,
        worktree=args.worktree,
        branch=args.branch,
        git_repo=args.git_repo,
        create_worktree=args.create_worktree,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
