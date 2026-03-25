from __future__ import annotations

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
        include_tags = ["llm"]

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


async def _run_single_problem(
    mcp_client: Client,
    llm_tools: list[dict[str, Any]],
    message: str,
    *,
    client_id: str,
    max_rounds: int = 16,
) -> tuple[list[dict[str, Any]], str]:
    messages: list[dict[str, Any]] = [{"role": "user", "content": message}]

    for _ in range(max_rounds):
        try:
            response = await client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=llm_tools,
                tool_choice="auto",
                temperature=0.7,
                top_p=0.8,
                max_tokens=4096,
                extra_body={
                    "repetition_penalty": 1.05,
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
            return messages, f"error:chat_completion:{type(error).__name__}"

        assistant_message = response.choices[0].message
        messages.append(_assistant_message_dict(assistant_message))

        stop_reason = response.choices[0].stop_reason
        if stop_reason is not None and stop_reason != "stop":
            return messages, stop_reason

        tool_calls = assistant_message.tool_calls
        if not tool_calls:
            return messages, "stop"

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

    messages.append(
        {
            "role": "assistant",
            "content": _tool_error_text(
                "max rounds exceeded",
                f"Exceeded max_rounds={max_rounds} while waiting for the model to stop requesting tools",
            ),
        }
    )
    return messages, "max_rounds_exceeded"


async def solve_messages_list(
    messages_list: list[str], concurrency: int = 4
) -> list[tuple[list[dict[str, Any]], str]]:
    semaphore = asyncio.Semaphore(concurrency)
    results: list[tuple[list[dict[str, Any]], str] | None] = [None] * len(messages_list)

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
                        results[index] = await _run_single_problem(
                            mcp_client,
                            llm_tools,
                            message,
                            client_id=client_id,
                        )
                    except Exception as error:
                        results[index] = build_error_result(
                            "solve_messages_list worker failed", error
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
    messages_list = [
        """Let $a, b, c, d$ be a permutation of the numbers $1, 9, 8, 4$. Define $n = (10a + b)^{10c + d}$. Calculate the probability that $1984!$ is divisible by $n$. Use Fermat's Little Theorem to assist in your calculations.""",
        """Compute \( \lim\limits_{n\to \infty} \int\limits_0^1 x^{2019} \{nx\} \, dx \), where \( \{a\} \) denotes the fractional part of the real number \( a \).""",
        """Let $E$ be the intersection of the cylinders $x^{2}+y^{2} \leq 1$ and $y^{2}+z^{2} \leq 1$. Compute the flux \( \iint_{\partial E} \vec{F} \cdot d\vec{S} \) where \( \vec{F} = (x y^{2} + \cos(y z)) \hat{i} - (x^{2} + \sin(z x)) \hat{j} + (z + \cos(x y)) \hat{k} \) and \( \partial E \) is oriented outward.""",
    ]
    results = await solve_messages_list(messages_list, concurrency=2)
    for result_messages, stop_reason in results:
        print("===============================================")
        print(f"stop_reason: {stop_reason}")
        print("messages:")
        print(json.dumps(result_messages, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
