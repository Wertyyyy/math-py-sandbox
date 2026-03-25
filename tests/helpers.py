from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport


WORKSPACE_DIR = Path(__file__).resolve().parents[1]
VENV_PYTHON = WORKSPACE_DIR / ".venv" / "bin" / "python"
SERVER_SCRIPT = WORKSPACE_DIR / "server.py"


class TestClient:
    def __init__(self, client: Client):
        self._client = client

    def __getattr__(self, name):
        return getattr(self._client, name)

    async def call_tool(self, name, arguments=None, **kwargs):
        kwargs.setdefault("raise_on_error", False)
        return await self._client.call_tool(name, arguments, **kwargs)


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
    return env


def ensure_test_environment() -> None:
    missing = [str(path) for path in (VENV_PYTHON, SERVER_SCRIPT) if not path.exists()]
    if missing:
        raise RuntimeError("Required test runtime files are missing: " + ", ".join(missing))


@asynccontextmanager
async def open_client_session(
    *,
    exec_timeout_seconds: int = 10,
    init_timeout_seconds: int = 20,
    process_time_limit_seconds: int = 600,
    max_sessions: int = 128,
) -> AsyncIterator[TestClient]:
    ensure_test_environment()
    transport = PythonStdioTransport(
        SERVER_SCRIPT,
        env=build_server_env(
            exec_timeout_seconds=exec_timeout_seconds,
            init_timeout_seconds=init_timeout_seconds,
            process_time_limit_seconds=process_time_limit_seconds,
            max_sessions=max_sessions,
        ),
        python_cmd=str(VENV_PYTHON),
    )

    async with Client(transport) as client:
        yield TestClient(client)
def tool_text(result) -> str:
    parts = []
    for item in result.content:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
        else:
            parts.append(str(item))
    return "".join(parts)


def tool_json(result):
    return json.loads(tool_text(result))
