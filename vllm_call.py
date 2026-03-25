from __future__ import annotations

import argparse
import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastmcp import Client
from openai import AsyncOpenAI

WORKSPACE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = WORKSPACE_DIR / ".venv" / "bin" / "python"
SERVER_SCRIPT = WORKSPACE_DIR / "server.py"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "EMPTY")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "http://localhost:8000/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "../models/Qwen3.5-27B")

client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_API_BASE,
)

SESSION_INFRA_STOP_REASON = "session_infra_error"
MAX_ROUNDS_STOP_REASON = "max_rounds_exceeded"


def build_server_env(
    *,
    exec_timeout_seconds: int = 10,
    init_timeout_seconds: int = 20,
    process_time_limit_seconds: int = 600,
    max_sessions: int = 128,
) -> dict[str, str]:
    env = os.environ.copy()
    env["EXEC_TIMEOUT_SECONDS"] = str(exec_timeout_seconds)
    env["INIT_TIMEOUT_SECONDS"] = str(init_timeout_seconds)
    env["PROCESS_TIME_LIMIT_SECONDS"] = str(process_time_limit_seconds)
    env["MAX_SESSIONS"] = str(max_sessions)
    env["NSJAIL_BIN"] = str(WORKSPACE_DIR / "nsjail" / "nsjail")
    env["HOST_VENV_PYTHON"] = str(VENV_PYTHON)
    env["HOST_REPL_RUNNER"] = str(
        WORKSPACE_DIR / "jail-root" / "app" / "repl_runner.py"
    )
    return env


def build_mcp_config(
    *,
    exec_timeout_seconds: int = 10,
    init_timeout_seconds: int = 20,
    process_time_limit_seconds: int = 600,
    max_sessions: int = 128,
    include_tags: list[str] | None = None,
    exclude_tags: list[str] | None = None,
    tool_transformations: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if include_tags is None:
        include_tags = ["llm", "internal"]

    server_config: dict[str, Any] = {
        "command": str(VENV_PYTHON),
        "args": [str(SERVER_SCRIPT)],
        "env": build_server_env(
            exec_timeout_seconds=exec_timeout_seconds,
            init_timeout_seconds=init_timeout_seconds,
            process_time_limit_seconds=process_time_limit_seconds,
            max_sessions=max_sessions,
        ),
    }
    if include_tags is not None:
        server_config["include_tags"] = include_tags
    if exclude_tags is not None:
        server_config["exclude_tags"] = exclude_tags
    if tool_transformations:
        server_config["tools"] = tool_transformations

    return {"mcpServers": {"python": server_config}}


@asynccontextmanager
async def open_mcp_client(
    *,
    exec_timeout_seconds: int = 10,
    init_timeout_seconds: int = 20,
    process_time_limit_seconds: int = 600,
    max_sessions: int = 128,
    include_tags: list[str] | None = None,
    exclude_tags: list[str] | None = None,
    tool_transformations: dict[str, dict[str, Any]] | None = None,
) -> AsyncIterator[Client]:
    if not VENV_PYTHON.exists():
        raise FileNotFoundError(f"venv python not found: {VENV_PYTHON}")
    if not SERVER_SCRIPT.exists():
        raise FileNotFoundError(f"server not found: {SERVER_SCRIPT}")

    config = build_mcp_config(
        exec_timeout_seconds=exec_timeout_seconds,
        init_timeout_seconds=init_timeout_seconds,
        process_time_limit_seconds=process_time_limit_seconds,
        max_sessions=max_sessions,
        include_tags=include_tags,
        exclude_tags=exclude_tags,
        tool_transformations=tool_transformations,
    )

    async with Client(config) as mcp_client:
        yield mcp_client


async def _load_llm_tools(mcp_client: Client) -> list[dict[str, Any]]:
    visible_tools = await mcp_client.list_tools()

    for tool in visible_tools:
        print("===============================================")
        print(f"Tool: {tool.name}")
        print(f"Description: \n{tool.description}")
        if getattr(tool, "inputSchema", None):
            print(f"Parameters: {tool.inputSchema}")
        if hasattr(tool, "meta") and tool.meta:
            fastmcp_meta = tool.meta.get("_fastmcp", {})
            print(f"Tags: {fastmcp_meta.get('tags', [])}")

    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": getattr(tool, "inputSchema", None)
                or {"type": "object", "properties": {}},
            },
        }
        for tool in visible_tools
        if "internal" not in (getattr(tool, "meta", {}) or {}).get("_fastmcp", {}).get("tags", [])
    ]


def _tool_result_text(result: Any) -> str:
    content = getattr(result, "content", None)
    if not content:
        return json.dumps(
            {
                "error": getattr(result, "error", None) or str(result),
                "context": "tool returned no structured content",
            },
            ensure_ascii=False,
        )

    parts: list[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
        else:
            parts.append(str(item))
    return "".join(parts)


def _tool_result_payload(result: Any) -> dict[str, Any] | None:
    try:
        payload = json.loads(_tool_result_text(result))
    except json.JSONDecodeError:
        return None

    return payload if isinstance(payload, dict) else None


def _tool_error_text(context: str, error: Exception | str) -> str:
    return json.dumps(
        {
            "error": str(error),
            "context": context,
        },
        ensure_ascii=False,
    )


def _assistant_message_dict(message: Any) -> dict[str, Any]:
    dumped_message = message.model_dump(exclude_none=True)
    return dumped_message


def _load_user_messages_from_jsonl(input_path: Path) -> list[str]:
    user_messages: list[str] = []
    with input_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSON at line {line_number} in {input_path}: {error}"
                ) from error

            messages = record.get("messages")
            if not isinstance(messages, list):
                raise ValueError(
                    f"Invalid record at line {line_number}: missing list field 'messages'"
                )

            user_content = None
            for message in messages:
                if isinstance(message, dict) and message.get("role") == "user":
                    user_content = message.get("content")
                    break

            if not isinstance(user_content, str) or not user_content.strip():
                raise ValueError(
                    f"Invalid record at line {line_number}: cannot find non-empty user message"
                )

            user_messages.append(user_content)

    return user_messages


def _write_single_final_message(
    output_dir: Path,
    index: int,
    result: tuple[list[dict[str, Any]], str | None],
) -> None:
    messages, finish_reason = result
    output_payload = {
        "index": index,
        "finish_reason": finish_reason,
        "messages": messages,
    }
    output_path = output_dir / f"sample_{index:06d}.json"
    output_path.write_text(
        json.dumps(output_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def _reset_client_session(mcp_client: Client, client_id: str) -> None:
    try:
        await mcp_client.call_tool(
            "python_reset_session",
            {},
            meta={"client_id": client_id},
            raise_on_error=False,
        )
    except Exception:
        pass


async def _run_single_problem(
    mcp_client: Client,
    llm_tools: list[dict[str, Any]],
    message: str,
    *,
    client_id: str,
    max_rounds: int = 16,
) -> tuple[list[dict[str, Any]], str | None]:
    """Solve one prompt and return the full message trace plus a stop reason.

    Stop reason contract:
    - Return the vLLM finish_reason immediately when it is not None and not "stop".
    - If the assistant message contains no tool calls, return the vLLM finish_reason as-is.
    - If a tool response reports `session_infrastructure_error`, return
            `session_infra_error`.
        - If a tool response reports `code_triggered_session_error` (including timeout-
            driven session termination), keep the conversation going and continue the loop.
    - If the model exceeds `max_rounds`, return `max_rounds_exceeded`.
        - If chat completion itself fails, return `chat_completion_error:<ExceptionName>`.
    """

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a math problem-solving assistant with access to tools. "
                "Use tools when they help your reasoning during the solving process, such as "
                "calculation, symbolic manipulation. "
                "Do not call tools only for a final after-the-fact validation if the solution "
                "is already complete. "
                "Please reason step by step, and put your final answer within \boxed{}."
            ),
        },
        {"role": "user", "content": message},
    ]
    try:
        for _ in range(max_rounds):
            try:
                # temperature=1.0, top_p=0.95, top_k=20, min_p=0.0, presence_penalty=1.5, repetition_penalty=1.0
                response = await client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=messages,
                    tools=llm_tools,
                    tool_choice="auto",
                    temperature=1.0,
                    top_p=0.95,
                    presence_penalty=1.5,
                    max_tokens=8192,
                    extra_body={
                        "repetition_penalty": 1.0,
                        "top_k": 20,
                        "min_p": 0.0,
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                )
            except Exception as error:
                messages.append(
                    {
                        "role": "assistant",
                        "content": _tool_error_text(
                            "chat completion request failed", error
                        ),
                    }
                )
                return messages, f"chat_completion_error:{type(error).__name__}"

            assistant_message = response.choices[0].message
            messages.append(_assistant_message_dict(assistant_message))

            finish_reason = response.choices[0].finish_reason
            if finish_reason != "tool_calls":
                return messages, finish_reason

            tool_calls = assistant_message.tool_calls
            if not tool_calls:
                return messages, finish_reason

            for tool_call in tool_calls:
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as error:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": _tool_error_text(
                                "Failed to parse tool arguments as JSON.", error
                            ),
                        }
                    )
                    continue

                try:
                    tool_result = await mcp_client.call_tool(
                        tool_call.function.name,
                        tool_args,
                        meta={"client_id": client_id},
                        raise_on_error=False,
                    )
                except Exception as error:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": _tool_error_text(
                                f"Tool call failed: {tool_call.function.name}", error
                            ),
                        }
                    )
                    continue

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": _tool_result_text(tool_result),
                    }
                )

                tool_payload = _tool_result_payload(tool_result)
                if tool_payload is None:
                    continue

                execution_status = tool_payload.get("execution_status")
                error_type = tool_payload.get("error_type")

                if execution_status == "session_error":
                    if error_type == "session_infrastructure_error":
                        return messages, SESSION_INFRA_STOP_REASON
                    if error_type == "code_triggered_session_error":
                        continue

        messages.append(
            {
                "role": "assistant",
                "content": _tool_error_text(
                    "max rounds exceeded",
                    f"Exceeded max_rounds={max_rounds} while waiting for the model to stop requesting tools",
                ),
            }
        )
        return messages, MAX_ROUNDS_STOP_REASON
    finally:
        await _reset_client_session(mcp_client, client_id)


async def solve_messages_list(
    messages_list: list[str],
    concurrency: int = 20,
    output_dir: Path | None = None,
) -> list[tuple[list[dict[str, Any]], str | None]]:
    semaphore = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()
    results: list[tuple[list[dict[str, Any]], str | None] | None] = [
        None
    ] * len(messages_list)

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    def build_error_result(
        context: str, error: Exception | str
    ) -> tuple[list[dict[str, Any]], str]:
        return (
            [
                {
                    "role": "assistant",
                    "content": _tool_error_text(context, error),
                }
            ],
            f"error:{context}:{type(error).__name__}"
            if isinstance(error, Exception)
            else f"error:{context}",
        )

    try:
        async with open_mcp_client() as mcp_client:
            try:
                llm_tools = await _load_llm_tools(mcp_client)
            except Exception as error:
                error_result = build_error_result("tool discovery failed", error)
                return [error_result for _ in messages_list]

            async def worker(index: int, message: str) -> None:
                async with semaphore:
                    client_id = f"message-{index + 1}"
                    try:
                        result = await _run_single_problem(
                            mcp_client,
                            llm_tools,
                            message,
                            client_id=client_id,
                        )
                        results[index] = result
                    except Exception as error:
                        result = build_error_result(
                            "solve_messages_list worker failed", error
                        )
                        results[index] = result

                    if output_dir is not None:
                        async with write_lock:
                            _write_single_final_message(
                                output_dir,
                                index + 1,
                                result,
                            )

            await asyncio.gather(
                *(worker(index, message) for index, message in enumerate(messages_list))
            )
    except Exception as error:
        error_result = build_error_result("mcp client startup failed", error)
        return [error_result for _ in messages_list]

    return [
        result
        or (
            [
                {
                    "role": "assistant",
                    "content": _tool_error_text(
                        "empty worker result", "unexpected empty result"
                    ),
                }
            ],
            "error:empty_result",
        )
        for result in results
    ]


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch solve JSONL math dataset and write per-sample final message JSON files."
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to input jsonl file. Each line must contain a 'messages' list.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./outputs"),
        help="Directory for per-sample output JSON files.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=100,
        help="Maximum number of concurrent requests.",
    )
    args = parser.parse_args()

    messages_list = _load_user_messages_from_jsonl(args.input)
    results = await solve_messages_list(
        messages_list,
        concurrency=args.concurrency,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "input": str(args.input),
                "output_dir": str(args.output_dir),
                "samples": len(results),
                "concurrency": args.concurrency,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
