"""AstrBot JM Comic 下载插件

在 QQ 私聊或群聊中发送 JM 码，自动下载漫画打包 ZIP 发送。
群聊需 @机器人。

命令:
  /jm_status <id>  — 查询任务状态
"""
import asyncio
import os
from typing import Optional

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import message_components as Comp
from astrbot.api import AstrBotConfig

from ._imports import ensure_jmcomic_import
from .task_manager import TaskManager, TaskStatus
from .downloader import download_and_zip


# 匹配 JM 码的 regex pattern string（传给 @filter.regex）
_JM_REGEX = r'(?i)(?:\bjm\d{4,}\b|\b\d{5,6}\b|https?://[^\s]*?(?:jm|18comic|comic)[^\s]*)'


@register("astrbot_plugin_jmcomic", "KiraLiang", "JM Comic 下载器 — 发送 JM 码下载漫画 ZIP", "1.0.0")
class JMPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config or {}
        self.task_manager: Optional[TaskManager] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._ready = asyncio.Event()

    async def _ensure_initialized(self):
        """延迟初始化"""
        if self._ready.is_set():
            return

        ensure_jmcomic_import(self.config if isinstance(self.config, dict) else {})

        db_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "jm_tasks.db"
        )
        self.task_manager = TaskManager(db_path)
        await self.task_manager.init()
        self._worker_task = asyncio.create_task(self._worker_loop())
        self._ready.set()

    def _get_config(self) -> dict:
        """获取配置字典"""
        return self.config if isinstance(self.config, dict) else {}

    # ==================== Worker ====================

    async def _worker_loop(self):
        """后台轮询任务队列，串行处理下载"""
        while True:
            try:
                await self._ready.wait()
                task = await self.task_manager.get_next_pending()
                if task is None:
                    await asyncio.sleep(2)
                    continue

                await self._process_task(task)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)

    async def _process_task(self, task):
        """处理单个下载任务"""
        config = self._get_config()
        try:
            album_name, zip_path, file_size = await download_and_zip(task.jm_id, config)

            await self.task_manager.update_status(
                task.task_id,
                TaskStatus.COMPLETED,
                album_name=album_name,
                file_path=zip_path,
                file_size=file_size,
            )

            await self._send_result(task, album_name, zip_path, file_size)

            if config.get("delete_after_send", True) and os.path.isfile(zip_path):
                try:
                    os.remove(zip_path)
                except OSError:
                    pass

        except Exception as e:
            import traceback
            err_msg = f"{type(e).__name__}: {e}"
            await self.task_manager.update_status(
                task.task_id, TaskStatus.FAILED, error=err_msg
            )
            await self._send_error(task, err_msg)
            traceback.print_exc()

    async def _send_result(self, task, album_name: str, zip_path: str, file_size: int):
        """主动发送下载完成的 ZIP 文件"""
        size_mb = file_size / (1024 * 1024)
        is_group = task.chat_type == "group"
        target_id = str(task.chat_id)

        # 发送文本通知
        try:
            await self.context.send_message(
                "aiocqhttp",
                [Comp.Plain(f"📦 《{album_name}》下载完成 ({size_mb:.1f}MB)")],
                target_id,
                is_group=is_group,
            )
        except Exception:
            pass

        # 发送 ZIP 文件
        try:
            await self.context.send_message(
                "aiocqhttp",
                [Comp.File(file=zip_path, name=f"{album_name}.zip")],
                target_id,
                is_group=is_group,
            )
        except Exception as e:
            try:
                await self.context.send_message(
                    "aiocqhttp",
                    [Comp.Plain(f"⚠ 文件发送失败 ({e})，ZIP 路径: {zip_path}")],
                    target_id,
                    is_group=is_group,
                )
            except Exception:
                pass

    async def _send_error(self, task, error: str):
        """发送下载失败通知"""
        is_group = task.chat_type == "group"
        target_id = str(task.chat_id)

        try:
            await self.context.send_message(
                "aiocqhttp",
                [Comp.Plain(f"❌ JM{task.jm_id} 下载失败: {error}")],
                target_id,
                is_group=is_group,
            )
        except Exception:
            pass

    # ==================== 消息处理 ====================

    @filter.regex(_JM_REGEX)
    async def on_jm_code(self, event: AstrMessageEvent):
        """匹配 JM 码，入队下载任务"""
        await self._ensure_initialized()

        # 群聊但未 @机器人，忽略
        if not event.is_private_chat() and not event.is_at_or_wake_command:
            return

        # 用 parse_to_jm_id 提取并验证 JM ID
        text = event.message_str.strip()
        try:
            from jmcomic.jm_toolkit import JmcomicText
            jm_id = JmcomicText.parse_to_jm_id(text)
        except Exception:
            return  # 不是有效的 JM 码，静默忽略

        # 确定聊天类型和 ID
        if event.is_private_chat():
            chat_type = "private"
            chat_id = event.get_sender_id()
        else:
            chat_type = "group"
            chat_id = event.get_group_id()

        # 入队（不预先获取漫画名，避免阻塞回复）
        task = await self.task_manager.enqueue(
            jm_id=jm_id,
            album_name="",
            chat_type=chat_type,
            chat_id=chat_id or "",
        )
        queue_pos = await self.task_manager.get_queue_position(task.task_id)

        # 快速回复
        if queue_pos > 0:
            msg = f"JM{jm_id} 已加入下载队列 (#{task.task_id})，前面还有 {queue_pos} 个任务"
        else:
            msg = f"JM{jm_id} 已加入下载队列 (#{task.task_id})，正在下载..."

        yield event.plain_result(msg)

    # ==================== 状态查询命令 ====================

    @filter.command("jm_status")
    async def on_status(self, event: AstrMessageEvent, task_id: str = ""):
        """查询下载任务状态。用法: /jm_status <任务号>"""
        await self._ensure_initialized()

        if not task_id:
            yield event.plain_result("用法: /jm_status <任务号>\n如: /jm_status 5")
            return

        try:
            tid = int(task_id.strip())
        except ValueError:
            yield event.plain_result(f"无效的任务号: {task_id}")
            return

        task = await self.task_manager.get_task(tid)
        if task is None:
            yield event.plain_result(f"任务 #{tid} 不存在")
            return

        name = task.album_name or f"JM{task.jm_id}"
        status_map = {
            TaskStatus.QUEUED: "排队中",
            TaskStatus.DOWNLOADING: "下载中",
            TaskStatus.COMPLETED: "已完成",
            TaskStatus.FAILED: "失败",
        }
        status_text = status_map.get(task.status, task.status.value)

        lines = [
            f"📋 任务 #{task.task_id}: {name}",
            f"状态: {status_text}",
        ]
        if task.file_size:
            lines.append(f"大小: {task.file_size / (1024 * 1024):.1f}MB")
        if task.error:
            lines.append(f"错误: {task.error}")

        yield event.plain_result("\n".join(lines))
