"""SQLite 持久化的下载任务队列"""
import asyncio
import os
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TaskStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class DownloadTask:
    """下载任务"""
    task_id: int
    jm_id: str
    album_name: str = ""
    status: TaskStatus = TaskStatus.QUEUED
    file_path: str = ""
    file_size: int = 0
    error: str = ""
    chat_type: str = "private"  # 'private' | 'group'
    chat_id: str = ""           # QQ号 或 群号
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class TaskManager:
    """基于 SQLite 的任务队列管理器"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = asyncio.Lock()

    def _get_conn(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    async def init(self) -> None:
        """初始化数据库表"""

        def _init():
            conn = self._get_conn()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        task_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                        jm_id      TEXT NOT NULL,
                        album_name TEXT DEFAULT '',
                        status     TEXT DEFAULT 'queued',
                        file_path  TEXT DEFAULT '',
                        file_size  INTEGER DEFAULT 0,
                        error      TEXT DEFAULT '',
                        chat_type  TEXT DEFAULT 'private',
                        chat_id    TEXT DEFAULT '',
                        created_at REAL DEFAULT 0,
                        updated_at REAL DEFAULT 0
                    )
                """)
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_init)

    async def enqueue(
        self,
        jm_id: str,
        album_name: str = "",
        chat_type: str = "private",
        chat_id: str = "",
    ) -> DownloadTask:
        """入队新任务，返回创建的任务对象"""

        def _enqueue():
            conn = self._get_conn()
            try:
                now = time.time()
                cursor = conn.execute(
                    """INSERT INTO tasks (jm_id, album_name, status, chat_type, chat_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (str(jm_id), album_name, TaskStatus.QUEUED.value, chat_type, chat_id, now, now),
                )
                conn.commit()
                task_id = cursor.lastrowid
                return DownloadTask(
                    task_id=task_id,
                    jm_id=str(jm_id),
                    album_name=album_name,
                    status=TaskStatus.QUEUED,
                    chat_type=chat_type,
                    chat_id=chat_id,
                    created_at=now,
                    updated_at=now,
                )
            finally:
                conn.close()

        async with self._lock:
            return await asyncio.to_thread(_enqueue)

    async def get_queue_position(self, task_id: int) -> int:
        """返回该任务前面还有多少个等待中的任务 (0-based)"""

        def _pos():
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM tasks WHERE status = 'queued' AND task_id < ?",
                    (task_id,),
                ).fetchone()
                return row["cnt"]
            finally:
                conn.close()

        return await asyncio.to_thread(_pos)

    async def get_next_pending(self) -> Optional[DownloadTask]:
        """取出队列最前面的待处理任务，并标记为 downloading"""

        async with self._lock:
            def _next():
                conn = self._get_conn()
                try:
                    row = conn.execute(
                        "SELECT * FROM tasks WHERE status = 'queued' ORDER BY task_id ASC LIMIT 1"
                    ).fetchone()
                    if row is None:
                        return None
                    # 标记为 downloading
                    now = time.time()
                    conn.execute(
                        "UPDATE tasks SET status = 'downloading', updated_at = ? WHERE task_id = ?",
                        (now, row["task_id"]),
                    )
                    conn.commit()
                    return DownloadTask(
                        task_id=row["task_id"],
                        jm_id=row["jm_id"],
                        album_name=row["album_name"],
                        status=TaskStatus.DOWNLOADING,
                        file_path=row["file_path"],
                        file_size=row["file_size"],
                        error=row["error"],
                        chat_type=row["chat_type"],
                        chat_id=row["chat_id"],
                        created_at=row["created_at"],
                        updated_at=now,
                    )
                finally:
                    conn.close()

            return await asyncio.to_thread(_next)

    async def update_status(
        self,
        task_id: int,
        status: TaskStatus,
        *,
        album_name: str = "",
        file_path: str = "",
        file_size: int = 0,
        error: str = "",
    ) -> None:
        """更新任务状态"""

        def _update():
            conn = self._get_conn()
            try:
                now = time.time()
                parts = ["status = ?", "updated_at = ?"]
                params = [status.value, now]

                if album_name:
                    parts.append("album_name = ?")
                    params.append(album_name)
                if file_path:
                    parts.append("file_path = ?")
                    params.append(file_path)
                if file_size:
                    parts.append("file_size = ?")
                    params.append(file_size)
                if error:
                    parts.append("error = ?")
                    params.append(error)

                params.append(task_id)
                conn.execute(
                    f"UPDATE tasks SET {', '.join(parts)} WHERE task_id = ?",
                    params,
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(_update)

    async def get_task(self, task_id: int) -> Optional[DownloadTask]:
        """查询单个任务"""

        def _get():
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
                ).fetchone()
                if row is None:
                    return None
                return DownloadTask(
                    task_id=row["task_id"],
                    jm_id=row["jm_id"],
                    album_name=row["album_name"],
                    status=TaskStatus(row["status"]),
                    file_path=row["file_path"],
                    file_size=row["file_size"],
                    error=row["error"],
                    chat_type=row["chat_type"],
                    chat_id=row["chat_id"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            finally:
                conn.close()

        return await asyncio.to_thread(_get)
