from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4
from pydantic import BaseModel


class PendingApproval(BaseModel):
    approval_id: str
    conversation_id: str
    tool_name: str
    args: dict[str, Any]


class ApprovalBroker:
    """Coordinates async HITL policy.ask_user requests with UI Approve/Deny actions."""

    def __init__(self, timeout_seconds: float = 600.0) -> None:
        self._timeout = timeout_seconds
        self._futures: dict[str, asyncio.Future[bool]] = {}
        self._metadata: dict[str, PendingApproval] = {}

    def list_pending(self, conversation_id: str | None = None) -> list[PendingApproval]:
        items = list(self._metadata.values())
        if conversation_id:
            return [m for m in items if m.conversation_id == conversation_id]
        return items

    async def request_approval(
        self,
        conversation_id: str,
        tool_name: str,
        args: dict[str, Any],
        emit_event: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> bool:
        approval_id = f"appr_{uuid4().hex[:12]}"
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bool] = loop.create_future()
        meta = PendingApproval(
            approval_id=approval_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            args=args,
        )
        self._futures[approval_id] = fut
        self._metadata[approval_id] = meta

        await emit_event(
            {
                "type": "approval_required",
                "approval_id": approval_id,
                "conversation_id": conversation_id,
                "tool_name": tool_name,
                "args": args,
            }
        )

        try:
            approved = await asyncio.wait_for(fut, timeout=self._timeout)
            await emit_event(
                {
                    "type": "approval_resolved",
                    "approval_id": approval_id,
                    "conversation_id": conversation_id,
                    "approved": approved,
                }
            )
            return approved
        except asyncio.TimeoutError:
            await emit_event(
                {
                    "type": "approval_resolved",
                    "approval_id": approval_id,
                    "conversation_id": conversation_id,
                    "approved": False,
                    "timed_out": True,
                }
            )
            return False
        finally:
            self._futures.pop(approval_id, None)
            self._metadata.pop(approval_id, None)

    def resolve(self, approval_id: str, approved: bool) -> bool:
        fut = self._futures.get(approval_id)
        if fut is None or fut.done():
            return False
        fut.set_result(bool(approved))
        return True

    def cancel_conversation(self, conversation_id: str) -> int:
        cancelled = 0
        for approval_id, meta in list(self._metadata.items()):
            if meta.conversation_id != conversation_id:
                continue
            fut = self._futures.get(approval_id)
            if fut is not None and not fut.done():
                fut.set_result(False)
                cancelled += 1
        return cancelled
