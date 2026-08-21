from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from tams_agent.connectivity import check_llm_connectivity
from tams_agent.llm import (
    create_anthropic_client,
    create_openai_client,
    describe_llm_target,
    get_active_config,
    llm_model,
    set_llm_overrides,
)
from tams_agent.llm_profiles import LlmOverrides, load_profiles_file
from tams_agent.mcp_client import TamsMcpClient


SYSTEM_PROMPT = """You are an attendance assistant for emaratech TAMS.
Use the available MCP tools to answer questions about employee attendance, reports, and settings.
Prefer get_daily_attendance or get_employee_wise_attendance for date-range attendance questions.
Return concise, structured answers. Include dates and counts when present in API data.
"""


def _load_env() -> None:
    for path in (Path.cwd() / ".env", Path("/app/.env"), Path(__file__).resolve().parents[3] / ".env"):
        if path.exists():
            load_dotenv(path)
            return
    load_dotenv()


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_mcp_command() -> list[str]:
    if shutil.which("tams-mcp"):
        return ["tams-mcp"]

    root = _workspace_root()
    venv_python = root / "mcp-server" / ".venv" / "bin" / "python"
    python = str(venv_python if venv_python.exists() else sys.executable)
    return [python, "-m", "tams_mcp.server"]


def _parse_verify_flag(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.lower() not in {"0", "false", "no", "off"}


def _build_cli_overrides(args: argparse.Namespace) -> LlmOverrides | None:
    if not any(
        [
            args.llm,
            args.model,
            args.llm_url,
            args.llm_key,
            args.llm_provider,
            args.llm_verify_ssl is not None,
            args.llm_timeout is not None,
        ]
    ):
        return None

    return LlmOverrides(
        profile=args.llm,
        provider=args.llm_provider,
        base_url=args.llm_url,
        model=args.model,
        api_key=args.llm_key,
        verify_ssl=_parse_verify_flag(args.llm_verify_ssl),
        timeout=float(args.llm_timeout) if args.llm_timeout is not None else None,
    )


def _print_llm_profiles() -> None:
    data = load_profiles_file()
    default = data.get("default")
    profiles = data.get("profiles", {})
    if default:
        print(f"default: {default}")
    if not profiles:
        print("No profiles found. Copy llm-profiles.example.json to llm-profiles.json")
        return
    for name, profile in sorted(profiles.items()):
        marker = " (default)" if name == default else ""
        provider = profile.get("provider", "openai")
        model = profile.get("model", "?")
        if provider == "anthropic":
            target = profile.get("base_url") or "api.anthropic.com"
        else:
            target = profile.get("base_url") or profile.get("url", "?")
        print(f"- {name}{marker}: provider={provider}, model={model}, target={target}")


def _print_llm_status() -> None:
    cfg = get_active_config()
    print(describe_llm_target())
    print(f"provider: {cfg.provider}")
    print(f"timeout: {cfg.timeout}s")


async def _run_openai(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
    client = create_openai_client()
    return client.chat.completions.create(
        model=llm_model(),
        messages=messages,
        tools=tools,
        tool_choice="auto",
    )


async def _run_anthropic(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
    cfg = get_active_config(default_model="claude-sonnet-4-20250514")
    client = create_anthropic_client()

    system = next((m["content"] for m in messages if m["role"] == "system"), SYSTEM_PROMPT)
    user_messages = [m for m in messages if m["role"] != "system"]

    anthropic_tools = []
    for tool in tools:
        fn = tool["function"]
        anthropic_tools.append(
            {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        )

    return client.messages.create(
        model=cfg.model,
        max_tokens=cfg.max_tokens,
        system=system,
        messages=user_messages,
        tools=anthropic_tools,
    )


def _to_openai_tools(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted = []
    for tool in mcp_tools:
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                },
            }
        )
    return converted


def _normalize_argv(argv: list[str]) -> list[str]:
    """Drop stray `--` tokens docker/compose sometimes injects before flags."""
    cleaned = list(argv)
    while len(cleaned) > 1 and cleaned[0] == "--":
        cleaned.pop(0)
    return cleaned


def _is_help_request(question: str, argv: list[str]) -> bool:
    if question in {"--help", "-h", "help"}:
        return True
    return any(token in {"-h", "--help"} for token in argv)


def _llm_error_message(exc: Exception) -> str:
    hint = ""
    msg = str(exc).lower()
    if "connection" in msg or "connect" in msg:
        hint = (
            " Hint: corporate/VPN URLs often fail inside Docker bridge network. "
            "Enable network_mode: host for the agent service, or run "
            "`tams-agent --check-llm` to diagnose."
        )
    return f"LLM request failed using {describe_llm_target()}: {exc}.{hint}"


async def run_agent(
    question: str,
    *,
    list_tools_only: bool = False,
    cli_overrides: LlmOverrides | None = None,
) -> None:
    _load_env()
    set_llm_overrides(cli_overrides)

    if not list_tools_only:
        print(f"Using {describe_llm_target()}")

    mcp = TamsMcpClient(_default_mcp_command())
    await mcp.connect()

    try:
        tools_raw = await mcp.list_tools()
        if list_tools_only:
            for tool in tools_raw:
                print(f"- {tool['name']}: {tool.get('description', '')}")
            return

        openai_tools = _to_openai_tools(tools_raw)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]

        provider = get_active_config().provider
        max_steps = int(os.getenv("AGENT_MAX_STEPS", "8"))

        for _ in range(max_steps):
            if provider == "anthropic":
                try:
                    response = await _run_anthropic(messages, openai_tools)
                except Exception as exc:
                    raise RuntimeError(_llm_error_message(exc)) from exc
                if response.stop_reason != "tool_use":
                    print(response.content[0].text)
                    return

                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    tool_result = await mcp.call_tool(block.name, block.input)
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": tool_result,
                                }
                            ],
                        }
                    )
            else:
                try:
                    response = await _run_openai(messages, openai_tools)
                except Exception as exc:
                    raise RuntimeError(_llm_error_message(exc)) from exc

                message = response.choices[0].message
                if not message.tool_calls:
                    print(message.content or "")
                    return

                messages.append(message.model_dump())
                for call in message.tool_calls:
                    args = json.loads(call.function.arguments or "{}")
                    tool_result = await mcp.call_tool(call.function.name, args)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": tool_result,
                        }
                    )

        print("Agent stopped after maximum tool steps.")
    finally:
        await mcp.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="TAMS attendance agent")
    parser.add_argument("question", nargs="?", default="", help="Natural language question")

    llm_group = parser.add_argument_group("LLM selection (on demand)")
    llm_group.add_argument("--llm", metavar="PROFILE", help="Use a named profile from llm-profiles.json")
    llm_group.add_argument("--model", help="Override model id for this run")
    llm_group.add_argument("--llm-url", help="Override OpenAI-compatible base URL for this run")
    llm_group.add_argument("--llm-key", help="Override API/JWT key for this run")
    llm_group.add_argument("--llm-provider", choices=["openai", "anthropic"], help="LLM provider for this run")
    llm_group.add_argument("--llm-verify-ssl", metavar="true|false", help="Override SSL verification")
    llm_group.add_argument("--llm-timeout", type=float, help="Override request timeout seconds")
    llm_group.add_argument("--list-llm-profiles", action="store_true", help="List configured LLM profiles")
    llm_group.add_argument("--show-llm", action="store_true", help="Show resolved LLM config and exit")
    llm_group.add_argument("--check-llm", action="store_true", help="Test DNS/TCP/HTTP connectivity to LLM and exit")

    parser.add_argument("--list-tools", action="store_true")
    argv = _normalize_argv(sys.argv[1:])
    args = parser.parse_args(argv)

    _load_env()
    cli_overrides = _build_cli_overrides(args)
    set_llm_overrides(cli_overrides)

    if args.list_llm_profiles:
        _print_llm_profiles()
        return

    if args.show_llm:
        _print_llm_status()
        return

    if args.check_llm:
        code = check_llm_connectivity()
        raise SystemExit(code)

    if args.list_tools:
        asyncio.run(run_agent("", list_tools_only=True, cli_overrides=cli_overrides))
        return

    if _is_help_request(args.question, argv):
        parser.print_help()
        return

    if not args.question:
        parser.error(
            "question is required unless using --list-tools, --list-llm-profiles, "
            "--show-llm, --check-llm, or -h"
        )

    if args.question == "tams-agent":
        parser.error(
            "Do not pass 'tams-agent' as the question. "
            "Use: docker compose --profile agent run --rm agent \"Your question here\""
        )

    asyncio.run(run_agent(args.question, cli_overrides=cli_overrides))


if __name__ == "__main__":
    main()
