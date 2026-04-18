"""Read-only Chainlit data layer backed by our SQLite DB.

Powers the native conversation-history sidebar in Chainlit.
New messages are still persisted by app.py; this layer only exposes
existing conversations for display and deletion.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

import db.queries as q
from utils.logger import get_logger

log = get_logger(__name__)

try:
    from chainlit.data.base import BaseDataLayer
    from chainlit.user import PersistedUser, User

    class SQLiteDataLayer(BaseDataLayer):

        # ── Users ─────────────────────────────────────────────────────────────

        async def get_user(self, identifier: str) -> Optional[PersistedUser]:
            row = await asyncio.to_thread(q.get_user, identifier)
            if not row:
                return None
            return PersistedUser(
                id=row["id"],
                identifier=row["id"],
                createdAt=row["created_at"],
            )

        async def create_user(self, user: User) -> Optional[PersistedUser]:
            row = await asyncio.to_thread(q.upsert_user, user.identifier)
            return PersistedUser(
                id=row["id"],
                identifier=row["id"],
                createdAt=row["created_at"],
            )

        # ── Threads (conversations) ────────────────────────────────────────────

        async def update_thread(
            self,
            thread_id: str,
            name: Optional[str] = None,
            user_id: Optional[str] = None,
            metadata: Optional[dict] = None,
            tags=None,
        ):
            if name:
                await asyncio.to_thread(q.update_conversation_title, thread_id, name)

        async def delete_thread(self, thread_id: str) -> bool:
            return await asyncio.to_thread(q.delete_conversation, thread_id)

        async def list_threads(self, pagination, filters):
            from chainlit.types import PaginatedResponse

            user_id = getattr(filters, "userId", None)
            if not user_id:
                return PaginatedResponse(
                    data=[], pageInfo={"hasNextPage": False, "endCursor": None}
                )
            limit = getattr(pagination, "first", 20) or 20
            rows = await asyncio.to_thread(q.list_conversations, user_id, limit)
            threads = [_conv_to_thread(r, user_id) for r in rows]
            return PaginatedResponse(
                data=threads, pageInfo={"hasNextPage": False, "endCursor": None}
            )

        async def get_thread(self, thread_id: str):
            row = await asyncio.to_thread(q.get_conversation, thread_id)
            if not row:
                return None
            return _conv_to_thread(row, row.get("user_id", ""), include_steps=True)

        async def get_thread_author(self, username: str) -> str:
            return username

        async def delete_user_session(self, id: str) -> bool:
            return True

        # ── Steps & elements — no-op (app.py owns persistence) ───────────────

        async def create_step(self, step_dict: dict):
            pass

        async def update_step(self, step_dict: dict):
            pass

        async def delete_step(self, step_id: str) -> bool:
            return True

        async def upsert_feedback(self, feedback) -> str:
            return getattr(feedback, "id", "") or ""

        async def create_element(self, element):
            pass

        async def update_element(self, element):
            pass

        async def delete_element(self, element_id: str, thread_id: Optional[str] = None) -> bool:
            return True

        async def get_element(self, thread_id: str, element_id: str):
            return None

        # ── Required stubs for newer Chainlit versions ────────────────────────

        async def build_debug_url(self) -> str:
            return ""

        async def close(self):
            pass

        async def delete_feedback(self, feedback_id: str) -> bool:
            return True

        async def get_favorite_steps(self) -> list:
            return []

except Exception as _import_err:
    SQLiteDataLayer = None  # type: ignore
    log.warning("Chainlit data layer unavailable — history sidebar disabled: %s", _import_err)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _conv_to_thread(row: dict, user_id: str, include_steps: bool = False) -> dict:
    steps = []
    if include_steps:
        for i, msg in enumerate(row.get("messages", [])):
            step_type = "user_message" if msg["role"] == "user" else "assistant_message"
            steps.append({
                "id": f"{row['id']}-{i}",
                "threadId": row["id"],
                "parentId": None,
                "type": step_type,
                "name": msg["role"],
                "output": msg["content"],
                "input": "",
                "createdAt": msg.get("ts", row.get("created_at", "")),
                "start": msg.get("ts", row.get("created_at", "")),
                "end": msg.get("ts", row.get("created_at", "")),
                "isError": False,
                "metadata": {},
            })
    return {
        "id": row["id"],
        "createdAt": row.get("created_at", ""),
        "name": row.get("title") or "Conversation",
        "userId": user_id,
        "userIdentifier": user_id,
        "tags": [],
        "metadata": {"model": row.get("model", "")},
        "steps": steps,
        "elements": [],
    }
