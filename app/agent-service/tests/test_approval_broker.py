from __future__ import annotations

import asyncio
from ag_workbench.approval_broker import ApprovalBroker


async def test_approval_broker_approve_flow() -> None:
    broker = ApprovalBroker(timeout_seconds=5.0)
    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)

    task = asyncio.create_task(
        broker.request_approval(
            conversation_id="conv-1",
            tool_name="edit_file",
            args={"TargetFile": "src/prompt.py"},
            emit_event=emit,
        )
    )

    while not broker.list_pending("conv-1"):
        await asyncio.sleep(0.01)

    pending = broker.list_pending("conv-1")
    assert len(pending) == 1
    approval_id = pending[0].approval_id

    assert broker.resolve(approval_id, True) is True
    assert broker.resolve(approval_id, False) is False  # Already resolved

    result = await task
    assert result is True
    assert events[0]["type"] == "approval_required"
    assert events[0]["tool_name"] == "edit_file"
    assert events[1]["type"] == "approval_resolved"
    assert events[1]["approved"] is True


async def test_approval_broker_deny_flow() -> None:
    broker = ApprovalBroker(timeout_seconds=5.0)
    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)

    task = asyncio.create_task(
        broker.request_approval(
            conversation_id="conv-2",
            tool_name="run_command",
            args={"command_line": "pytest"},
            emit_event=emit,
        )
    )

    while not broker.list_pending("conv-2"):
        await asyncio.sleep(0.01)

    approval_id = broker.list_pending("conv-2")[0].approval_id
    assert broker.resolve(approval_id, False) is True
    assert await task is False
    assert events[-1]["approved"] is False


async def test_approval_broker_cancel_conversation() -> None:
    broker = ApprovalBroker(timeout_seconds=5.0)
    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)

    task = asyncio.create_task(
        broker.request_approval(
            conversation_id="conv-cancel",
            tool_name="edit_file",
            args={"TargetFile": "src/app.py"},
            emit_event=emit,
        )
    )

    while not broker.list_pending("conv-cancel"):
        await asyncio.sleep(0.01)

    assert broker.cancel_conversation("conv-cancel") == 1
    assert broker.cancel_conversation("conv-cancel") == 0
    assert await task is False
