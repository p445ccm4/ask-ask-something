from __future__ import annotations

from google.antigravity.hooks import hooks, policy
from google.antigravity.types import BuiltinTools, ToolCall

from ask_workbench.agent_runner import (
    build_capabilities,
    build_host_tools,
    build_policies,
    build_system_instructions,
    is_destructive_command,
)
from ag_workbench.approval_broker import ApprovalBroker
from ask_workbench.uat_service import UatService
from ask_workbench.workspaces import WorkspaceEntry


def test_is_destructive_command_catches_git_push_and_rm() -> None:
    assert is_destructive_command({"command_line": "git push origin main"}) is True
    assert is_destructive_command({"CommandLine": "git add . && git push"}) is True
    assert is_destructive_command({"command_line": "rm -rf /tmp/foo"}) is True
    assert is_destructive_command({"command_line": "git reset --hard HEAD~1"}) is True
    assert is_destructive_command({"command_line": "gcloud run deploy svc"}) is True
    assert is_destructive_command({"command_line": "pytest -q"}) is False
    assert is_destructive_command({"command_line": "git diff src/"}) is False


async def test_sandboxed_auto_blocks_git_push_but_allows_pytest() -> None:
    broker = ApprovalBroker()

    async def emit(_: dict) -> None:
        return None

    caps = build_capabilities("sandboxed_auto")
    assert caps.run_command_config is not None
    assert caps.run_command_config.enable_sandbox is True

    policies = build_policies("sandboxed_auto", "conv-1", broker, emit)
    hook = policy.enforce(policies)

    res_push = await hook.run(
        hooks.HookContext(),
        ToolCall(name="run_command", args={"command_line": "git push origin main"}),
    )
    assert res_push.allow is False
    assert "Deploy buttons" in (res_push.message or "")

    res_pytest = await hook.run(
        hooks.HookContext(),
        ToolCall(name="run_command", args={"command_line": "uv run pytest"}),
    )
    assert res_pytest.allow is True


async def test_unsandboxed_auto_disables_sandbox_and_allows_commands() -> None:
    broker = ApprovalBroker()

    async def emit(_: dict) -> None:
        return None

    caps = build_capabilities("unsandboxed_auto")
    assert caps.run_command_config is not None
    assert caps.run_command_config.enable_sandbox is False
    assert BuiltinTools.RUN_COMMAND in (caps.enabled_tools or [])

    policies = build_policies("unsandboxed_auto", "conv-1", broker, emit)
    hook = policy.enforce(policies)

    res_cmd = await hook.run(
        hooks.HookContext(),
        ToolCall(name="run_command", args={"command_line": "uv run pytest"}),
    )
    assert res_cmd.allow is True

    res_edit = await hook.run(hooks.HookContext(), ToolCall(name="edit_file", args={}))
    assert res_edit.allow is True


def test_build_system_instructions_supports_all_four_modes() -> None:
    ws = WorkspaceEntry(id="ws", name="Sample Agent", path="/tmp/sample")
    for mode in ("read_only", "ask_before_fix", "sandboxed_auto", "unsandboxed_auto"):
        text = build_system_instructions(ws, mode)  # type: ignore[arg-type]
        assert "Sample Agent" in text
        assert "attach_output_file" in text
        assert ".ag-artifacts/" in text


async def test_read_only_mode_blocks_writes_and_run_command() -> None:
    broker = ApprovalBroker()

    async def emit(_: dict) -> None:
        return None

    caps = build_capabilities("read_only")
    assert BuiltinTools.RUN_COMMAND not in (caps.enabled_tools or [])
    assert BuiltinTools.EDIT_FILE not in (caps.enabled_tools or [])
    assert BuiltinTools.VIEW_FILE in (caps.enabled_tools or [])

    policies = build_policies("read_only", "conv-1", broker, emit)
    hook = policy.enforce(policies)

    for tool_name in ("edit_file", "create_file", "run_command", "run_uat_check"):
        res = await hook.run(hooks.HookContext(), ToolCall(name=tool_name, args={}))
        assert res.allow is False

    res_read = await hook.run(hooks.HookContext(), ToolCall(name="view_file", args={"AbsolutePath": "a.py"}))
    assert res_read.allow is True


def test_deploy_service_never_exposed_to_agent_tools() -> None:
    ws = WorkspaceEntry(id="ws", name="Sample Agent", path="/tmp")
    uat = UatService()
    for mode in ("read_only", "ask_before_fix", "sandboxed_auto", "unsandboxed_auto"):
        tool_names = {fn.__name__ for fn in build_host_tools(ws, uat, mode)}  # type: ignore[arg-type]
        assert "execute_deploy" not in tool_names
        assert "preview_deploy" not in tool_names
    assert "run_uat_check" not in {fn.__name__ for fn in build_host_tools(ws, uat, "read_only")}
    assert "run_uat_check" in {fn.__name__ for fn in build_host_tools(ws, uat, "ask_before_fix")}
    assert "run_uat_check" in {fn.__name__ for fn in build_host_tools(ws, uat, "unsandboxed_auto")}
