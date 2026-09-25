"""cockpit.omo_write_guard — .omo 写入契约薄守卫 (P2 并发安全).

职责:
  · 统一 .omo 下 jsonl / yaml / text 的写入入口;
  · 提供最小 advisory-lock 语义, 防止多进程并发 append 损坏 jsonl;
  · 不改变现有业务语义, 仅包裹写入动作.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


class OmoWriteGuardError(Exception):
    """ .omo 写入守卫异常."""


def _lock_path(target: Path) -> Path:
    """为目标文件生成同目录 .lock 文件路径."""
    return target.with_suffix(target.suffix + ".lock")


def _acquire_lock(lock: Path, timeout: float = 5.0) -> bool:
    """简易阻塞锁: 通过 mkdir 原子性实现 (cross-platform).

    timeout 秒内轮询, 拿到锁返回 True, 超时返回 False.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            lock.mkdir(parents=True, exist_ok=False)
            return True
        except FileExistsError:
            time.sleep(0.05)
        except (OSError, ValueError):
            time.sleep(0.05)
    return False


def _release_lock(lock: Path) -> None:
    """释放锁目录 (最佳 effort, 不抛异常)."""
    try:
        lock.rmdir()
    except (OSError, FileNotFoundError):
        pass


def ensure_omo_dir(omo_root: Path, *subparts: str) -> Path:
    """确保 .omo 下某个子目录存在, 返回完整路径."""
    target = omo_root.joinpath(*subparts)
    target.mkdir(parents=True, exist_ok=True)
    return target


def append_jsonl(omo_root: Path, *subparts: str, record: dict[str, Any], lock_timeout: float = 5.0) -> Path:
    """原子追加一条 JSON 行到 .omo 下 jsonl 文件.

    Args:
      omo_root: .omo 根目录 (通常为 WORKSPACE_ROOT / ".omo").
      subparts: 相对路径段, 如 ("_knowledge", "bos-metrics.jsonl").
      record: 要追加的 dict, 会被 json.dumps + newline.
      lock_timeout: 获取锁的超时秒数.

    Returns:
      写入文件的完整路径.

    Raises:
      OmoWriteGuardError: 目录创建失败 / 锁获取超时 / 写入失败.
    """
    target = ensure_omo_dir(omo_root, *subparts[:-1]) / subparts[-1]
    lock = _lock_path(target)
    if not _acquire_lock(lock, timeout=lock_timeout):
        raise OmoWriteGuardError(f"获取写入锁超时: {lock}")
    try:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with target.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            try:
                f.flush()
                os.fsync(f.fileno())
            except (OSError, AttributeError):
                pass
    except (OSError, TypeError) as exc:
        raise OmoWriteGuardError(f"写入失败 {target}: {exc}") from exc
    finally:
        _release_lock(lock)
    return target


def write_text(omo_root: Path, *subparts: str, content: str, encoding: str = "utf-8") -> Path:
    """写入文本文件到 .omo 下 (覆盖写入, 非追加)."""
    target = ensure_omo_dir(omo_root, *subparts[:-1]) / subparts[-1]
    try:
        target.write_text(content, encoding=encoding)
    except (OSError, TypeError) as exc:
        raise OmoWriteGuardError(f"写入失败 {target}: {exc}") from exc
    return target


def write_json(omo_root: Path, *subparts: str, data: Any, encoding: str = "utf-8") -> Path:
    """写入 JSON 文件到 .omo 下 (覆盖写入, 带缩进)."""
    return write_text(omo_root, *subparts, content=json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding=encoding)
