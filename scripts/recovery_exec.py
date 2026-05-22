#!/usr/bin/env python3
"""
recovery_exec.py — 人工触发 recovery 动作（resume / rollback / abort）。

Worktree-aware 版本：支持 per-task git worktree 隔离的 rollback。

新增 worktree 模式行为：
    resume：   将任务重新派发，附带 worktree 路径信息
    rollback： 在 worktree 内 git checkout {上一个commit}，然后重新派发
    abort：    清理 worktree，将任务标记为终止

用法：
    python recovery_exec.py --task-id <id> --action <resume|rollback|abort>
"""

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


HERMES_HOME = Path.home() / ".hermes"
KANBAN_DB = HERMES_HOME / "kanban.db"


VALID_ACTIONS = {"resume", "rollback", "abort"}


def get_task(task_id: str) -> dict | None:
    conn = sqlite3.connect(KANBAN_DB)
    row = conn.execute(
        """
        SELECT id, stage, checkpoint_data, last_checkpoint_at, checkpoint_status, status
        FROM tasks WHERE id = ?
        """,
        (task_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "id": row[0],
        "stage": row[1],
        "checkpoint_data": row[2],
        "last_checkpoint_at": row[3],
        "checkpoint_status": row[4],
        "status": row[5],
    }


def mark_resolved(task_id: str):
    conn = sqlite3.connect(KANBAN_DB)
    conn.execute(
        "UPDATE tasks SET checkpoint_status = 'resolved' WHERE id = ?",
        (task_id,),
    )
    conn.commit()
    conn.close()


def _git_checkout(worktree_path: str, ref: str) -> tuple[bool, str]:
    """在 worktree 内执行 git checkout。返回 (成功, 错误信息)。"""
    try:
        result = subprocess.run(
            ["git", "-C", worktree_path, "checkout", ref],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr.strip()
    except Exception as e:
        return False, str(e)


def _remove_worktree(worktree_path: str, repo_path: str) -> tuple[bool, str]:
    """删除 worktree。返回 (成功, 错误信息)。"""
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "worktree", "remove", worktree_path, "--force"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr.strip()
    except Exception as e:
        return False, str(e)


def abort_task(task_id: str, checkpoint_data: dict):
    """
    abort：将任务标记为终止，清理 worktree。
    """
    worktree = checkpoint_data.get("worktree")
    git_repo = checkpoint_data.get("git_repo", str(HERMES_HOME))

    # 尝试清理 worktree
    if worktree:
        ok, err = _remove_worktree(worktree, git_repo)
        if ok:
            print(f"[ABORT] worktree 已清理: {worktree}")
        else:
            print(f"[WARN] worktree 清理失败: {err}", file=sys.stderr)

    conn = sqlite3.connect(KANBAN_DB)
    now = time.time()
    conn.execute(
        "UPDATE tasks SET "
        "  status = 'done', "
        "  checkpoint_status = 'resolved', "
        "  completed_at = ? "
        "WHERE id = ?",
        (now, task_id),
    )
    conn.commit()
    conn.close()
    print(f"[ABORT] 任务 {task_id} 已终止")


def resume_task(task_id: str, checkpoint_data: dict):
    """
    resume：将 checkpoint_status 改回 active，下次 dispatcher tick 会重新派发。
    如果有 worktree，在重新派发时告知 worktree 路径。
    """
    worktree = checkpoint_data.get("worktree")
    branch = checkpoint_data.get("branch")
    git_repo = checkpoint_data.get("git_repo", str(HERMES_HOME))

    conn = sqlite3.connect(KANBAN_DB)
    now = time.time()

    # 更新 checkpoint_data 加入 resume 标记
    cp_data = dict(checkpoint_data)
    cp_data["resume_count"] = cp_data.get("resume_count", 0) + 1
    cp_data["last_resume_at"] = now

    conn.execute(
        "UPDATE tasks SET "
        "  status = 'ready', "
        "  checkpoint_status = 'active', "
        "  last_checkpoint_at = ?, "
        "  checkpoint_data = ? "
        "WHERE id = ?",
        (now, json.dumps(cp_data), task_id),
    )
    conn.commit()
    conn.close()

    msg = f"[RESUME] 任务 {task_id} 已重新派发，从 stage \"{checkpoint_data.get('next_step', 'N/A')}\" 继续"
    if worktree:
        msg += f"\n       worktree: {worktree} (branch: {branch})"
    print(msg)


def rollback_task(task_id: str, checkpoint_data: dict):
    """
    rollback：在 worktree 内 git checkout {commit}，然后重新派发。

    如果没有 worktree 信息，退化到旧行为（只重新派发）。
    """
    worktree = checkpoint_data.get("worktree")
    commit = checkpoint_data.get("commit")
    git_repo = checkpoint_data.get("git_repo", str(HERMES_HOME))

    if not worktree or not commit:
        print("[WARN] 无 worktree 信息，退化到纯重新派发模式")
        conn = sqlite3.connect(KANBAN_DB)
        now = time.time()
        conn.execute(
            "UPDATE tasks SET "
            "  status = 'ready', "
            "  checkpoint_status = 'active', "
            "  last_checkpoint_at = ? "
            "WHERE id = ?",
            (now, task_id),
        )
        conn.commit()
        conn.close()
        print(f"[ROLLBACK] 任务 {task_id} 已回滚（无 worktree）")
        return

    # 在 worktree 内执行 git checkout
    print(f"[ROLLBACK] worktree 内回滚到 commit {commit} ...")
    ok, err = _git_checkout(worktree, commit)
    if not ok:
        print(f"[ERROR] git checkout 失败: {err}", file=sys.stderr)
        sys.exit(1)

    print(f"[ROLLBACK] git checkout {commit} 成功")

    # 重新派发
    conn = sqlite3.connect(KANBAN_DB)
    now = time.time()

    cp_data = dict(checkpoint_data)
    cp_data["rollback_count"] = cp_data.get("rollback_count", 0) + 1
    cp_data["last_rollback_at"] = now
    cp_data["rollback_to_commit"] = commit

    conn.execute(
        "UPDATE tasks SET "
        "  status = 'ready', "
        "  checkpoint_status = 'active', "
        "  last_checkpoint_at = ?, "
        "  checkpoint_data = ? "
        "WHERE id = ?",
        (now, json.dumps(cp_data), task_id),
    )
    conn.commit()
    conn.close()

    print(f"[ROLLBACK] 任务 {task_id} 已回滚并重新派发，从 stage \"{checkpoint_data.get('next_step', 'N/A')}\" 继续")
    print(f"       worktree: {worktree}")


def main():
    parser = argparse.ArgumentParser(description="执行 recovery 动作（worktree-aware）")
    parser.add_argument("--task-id", required=True, help="Kanban 任务 ID")
    parser.add_argument(
        "--action",
        required=True,
        choices=["resume", "rollback", "abort"],
        help="动作：resume（继续）/ rollback（回滚）/ abort（终止）",
    )
    args = parser.parse_args()

    if not KANBAN_DB.exists():
        print(f"[ERROR] kanban.db not found: {KANBAN_DB}", file=sys.stderr)
        sys.exit(1)

    task = get_task(args.task_id)
    if task is None:
        print(f"[ERROR] task not found: {args.task_id}", file=sys.stderr)
        sys.exit(1)

    if task["status"] == "done":
        print(f"[ERROR] 任务 {args.task_id} 已完成，无法执行 recovery", file=sys.stderr)
        sys.exit(1)

    cp_data = {}
    if task["checkpoint_data"]:
        try:
            cp_data = json.loads(task["checkpoint_data"])
        except (json.JSONDecodeError, TypeError):
            cp_data = {}

    action = args.action

    if action == "abort":
        abort_task(args.task_id, cp_data)
        sys.exit(0)

    if action == "resume":
        resume_task(args.task_id, cp_data)
        sys.exit(0)

    if action == "rollback":
        rollback_task(args.task_id, cp_data)
        sys.exit(0)


if __name__ == "__main__":
    main()
