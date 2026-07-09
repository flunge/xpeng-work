from __future__ import annotations

from app.domain.models import ExecutionResult, TaskRun
from app.infrastructure.feishu_clients import FeishuDocClient, FeishuMessageClient, FeishuSheetClient, MessageDispatchResult
from app.infrastructure.feishu_config import FeishuSettings


class SyncService:
    def __init__(
        self,
        message_client: FeishuMessageClient,
        doc_client: FeishuDocClient,
        sheet_client: FeishuSheetClient,
        settings: FeishuSettings | None = None,
    ) -> None:
        self.message_client = message_client
        self.doc_client = doc_client
        self.sheet_client = sheet_client
        self.settings = settings or FeishuSettings()

    def sync(self, task: TaskRun, result: ExecutionResult | None = None) -> dict:
        wants_doc = bool(task.params.get("wants_doc"))

        if wants_doc:
            task.doc_url = self.doc_client.upsert_task_doc(task, result)

        message = self.message_client.send_task_update(task, result)
        if isinstance(message, MessageDispatchResult):
            task.sync_message_id = message.message_id

        row = self.sheet_client.upsert_task_row(task)
        if isinstance(row, dict):
            task.sync_record_id = row.get("record_id") or row.get("record", {}).get("record_id") or task.sync_record_id

        return {
            "message": message,
            "sheet_row": row,
            "doc_url": task.doc_url,
            "sync_message_id": task.sync_message_id,
            "sync_record_id": task.sync_record_id,
        }

    @staticmethod
    def wants_doc_output(text: str) -> bool:
        doc_keywords = (
            "输出报告",
            "生成报告",
            "写报告",
            "报告文档",
            "输出文档",
            "生成文档",
            "创建文档",
            "飞书文档",
            "整理成文档",
            "保存成文档",
            "输出成文档",
            "写成文档",
            "整理为文档",
        )
        return any(keyword in text for keyword in doc_keywords)

    def reply_busy(self, task: TaskRun) -> MessageDispatchResult:
        return self.message_client.reply_text(
            message_id=task.message_id,
            chat_id=task.chat_id,
            text=self.settings.busy_reply_text,
            reply_in_thread=self.settings.reply_in_thread,
        )

    def send_bootstrap_greeting(self) -> MessageDispatchResult | None:
        if not self.settings.enable_bootstrap_greeting:
            return None
        if self.settings.bootstrap_target_open_id:
            return self.message_client.send_text_to_user(
                user_id=self.settings.bootstrap_target_open_id,
                text=self.settings.bootstrap_greeting,
            )
        if self.settings.bootstrap_target_chat_id:
            return self.message_client.send_text_to_chat(
                chat_id=self.settings.bootstrap_target_chat_id,
                text=self.settings.bootstrap_greeting,
            )
        if self.settings.bootstrap_target_name:
            return self.message_client.send_text_to_user_name(
                name=self.settings.bootstrap_target_name,
                text=self.settings.bootstrap_greeting,
            )
        return None
