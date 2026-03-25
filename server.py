import subprocess
import os
import json
import threading
import time
import base64
from typing import Dict

from fastmcp import Context, FastMCP

os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "4")


# -----------------------------
# Configuration
# -----------------------------
HOST_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
NSJAIL_BIN = os.path.join(HOST_PROJECT_DIR, "nsjail", "nsjail")
HOST_VENV_PYTHON = os.path.join(HOST_PROJECT_DIR, ".venv", "bin", "python")
HOST_REPL_RUNNER = os.path.join(HOST_PROJECT_DIR, "jail-root", "app", "repl_runner.py")

THREAD_ENV_VARS = [
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
]


# -----------------------------
# Session management
# -----------------------------


class PythonSession:
    def __init__(
        self,
    ):
        self.nsjail_bin = os.getenv("NSJAIL_BIN", NSJAIL_BIN)
        self.host_venv_python = os.getenv("HOST_VENV_PYTHON", HOST_VENV_PYTHON)
        self.host_repl_runner = os.getenv("HOST_REPL_RUNNER", HOST_REPL_RUNNER)
        self.exec_timeout_seconds = int(os.getenv("EXEC_TIMEOUT_SECONDS", "10"))
        self.init_timeout_seconds = int(os.getenv("INIT_TIMEOUT_SECONDS", "20"))
        self.process_time_limit_seconds = int(
            os.getenv("PROCESS_TIME_LIMIT_SECONDS", "600")
        )
        self.proc = self._start_process()
        self.lock = threading.Lock()
        self._wait_until_ready()

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.init_timeout_seconds

        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close()
                raise RuntimeError(
                    f"Python session startup timed out after {self.init_timeout_seconds} seconds"
                )

            import select

            ready, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if not ready:
                self.close()
                raise RuntimeError(
                    f"Python session startup timed out after {self.init_timeout_seconds} seconds"
                )

            line = self.proc.stdout.readline()
            if not line:
                self.close()
                raise RuntimeError("Python session failed to start")

            response = json.loads(line)
            if response.get("type") == "ready":
                return

            self.close()
            raise RuntimeError(f"Unexpected response during initialization: {response}")
        except json.JSONDecodeError:
            self.close()
            raise RuntimeError(
                f"Invalid JSON from repl_runner during initialization: {line}"
            )
        except Exception as e:
            self.close()
            raise RuntimeError(f"Failed to initialize Python session: {str(e)}")

    def _start_process(self) -> subprocess.Popen:
        return subprocess.Popen(
            [
                self.nsjail_bin,
                "--quiet",
                "--time_limit",
                str(self.process_time_limit_seconds),
                "--keep_env",
                *[item for name in THREAD_ENV_VARS for item in ("--env", name)],
                "--disable_clone_newuser",
                "--disable_clone_newnet",
                "--disable_clone_newns",
                "--disable_clone_newpid",
                "--disable_clone_newipc",
                "--disable_clone_newuts",
                "--disable_clone_newcgroup",
                "--",
                self.host_venv_python,
                "-u",
                self.host_repl_runner,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def execute(self, code: str) -> str:
        with self.lock:
            if self.proc.poll() is not None:
                raise RuntimeError("Python session terminated")

            code_b64 = base64.b64encode(code.encode("utf-8")).decode("ascii")
            request = json.dumps({"type": "execute", "code": code_b64})
            self.proc.stdin.write(request + "\n")
            self.proc.stdin.flush()

            deadline = time.monotonic() + self.exec_timeout_seconds
            response_line = ""

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.close()
                    raise RuntimeError(
                        f"Execution timed out after {self.exec_timeout_seconds} seconds"
                    )

                import select

                ready, _, _ = select.select([self.proc.stdout], [], [], remaining)
                if not ready:
                    self.close()
                    raise RuntimeError(
                        f"Execution timed out after {self.exec_timeout_seconds} seconds"
                    )

                response_line = self.proc.stdout.readline()
                if not response_line:
                    self.close()
                    raise RuntimeError("Python session terminated unexpectedly")

                break

            try:
                response = json.loads(response_line)
            except json.JSONDecodeError:
                self.close()
                raise RuntimeError(
                    f"Invalid JSON response from repl_runner: {response_line}"
                )

            response_type = response.get("type")

            if response_type == "success":
                return response.get("output", "")

            elif response_type == "error":
                if "error" not in response:
                    self.close()
                    raise RuntimeError(
                        "Error response missing 'error' field from repl_runner"
                    )
                raise CodeExecutionError(response["error"])

            else:
                self.close()
                raise RuntimeError(
                    f"Unexpected response type from repl_runner: {response_type}"
                )

    def close(self):
        try:
            if self.proc and self.proc.poll() is None:
                request = json.dumps({"type": "exit"})
                self.proc.stdin.write(request + "\n")
                self.proc.stdin.flush()
                self.proc.terminate()
        except Exception:
            pass


MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "128"))

sessions: Dict[str, PythonSession] = {}
sessions_lock = threading.Lock()


def _session_is_alive(session: PythonSession) -> bool:
    return session.proc.poll() is None


def _prune_dead_sessions_unlocked() -> None:
    dead_session_ids = [
        session_id
        for session_id, session in sessions.items()
        if not _session_is_alive(session)
    ]
    for session_id in dead_session_ids:
        sessions.pop(session_id, None)


def _require_client_id(ctx: Context) -> str:
    client_id = ctx.client_id
    if not client_id:
        raise RuntimeError("client_id is required to manage a Python session")
    return client_id


def _spawn_session() -> PythonSession:
    return PythonSession()


class CodeExecutionError(RuntimeError):
    """Code execution failed while the interpreter session remains healthy."""


def _get_or_create_session(session_id: str) -> tuple[PythonSession, bool]:
    with sessions_lock:
        _prune_dead_sessions_unlocked()

        existing_session = sessions.get(session_id)
        if existing_session is not None and _session_is_alive(existing_session):
            return existing_session, False

        if existing_session is not None:
            existing_session.close()
            sessions.pop(session_id, None)

        if len(sessions) >= MAX_SESSIONS:
            raise RuntimeError(
                f"Maximum active session limit reached ({MAX_SESSIONS}). "
                "Please reset an existing session before creating a new one."
            )

        new_session = _spawn_session()
        sessions[session_id] = new_session
        return new_session, True


def _reset_session(session_id: str) -> bool:
    with sessions_lock:
        session = sessions.pop(session_id, None)

    if session is None:
        return False

    session.close()
    return True


# -----------------------------
# MCP Tools
# -----------------------------

mcp = FastMCP("python")

CODE_EXEC_SUCCESS = "The code executed successfully. The session remains active and all variables/definitions are preserved for subsequent calls."
CODE_EXEC_ERROR = "The code execution failed. The session remains active; previously created variables are preserved."
SESSION_ERROR = "The session has been terminated and all resources are freed. Please redefine all functions and variables in a new session on your next call."


def _python_exec_success(output: str) -> str:
    return json.dumps(
        {
            "interpreter_output": output,
            "session_status": "active",
            "execution_status": "success",
            "error_type": None,
            "error_message": None,
        }
    )


def _python_exec_code_error(output: str) -> str:
    return json.dumps(
        {
            "interpreter_output": output,
            "session_status": "active",
            "execution_status": "code_error",
            "error_type": "code_execution_error",
            "error_message": CODE_EXEC_ERROR,
        }
    )


def _python_exec_session_error(
    *,
    error_type: str,
    error_message: str,
    session_status: str,
) -> str:
    return json.dumps(
        {
            "interpreter_output": None,
            "session_status": session_status,
            "execution_status": "session_error",
            "error_type": error_type,
            "error_message": error_message,
        }
    )


def _is_code_triggered_session_error(error_message: str) -> bool:
    lowered = error_message.lower()
    return (
        "timed out" in lowered
        or "terminated unexpectedly" in lowered
        or "python session terminated" in lowered
    )

@mcp.tool(tags={"llm"})
def python_exec(code: str, ctx: Context) -> str:
    """
    This tool runs Python code in an isolated, sandboxed environment using nsjail.
    Multiple code executions can be performed in the same session, preserving variables
    and state between calls. Each client gets its own session, keyed by client_id.

    The execution environment includes numpy, scipy, and sympy. No other third-party
    libraries are available.

    Parameters:
    -----------
    code : str
        Python code to execute as a string. Can include multiple lines, imports,
        function definitions, loops, etc. Any print output is captured and returned.
        Please import any required libraries (e.g. numpy, scipy, sympy) within 
        the code string.
        Please print the final results to stdout, as only print output is captured 
        and returned.

        Examples of valid code:
        - "print('hello')"
        - "import math; print(math.sqrt(16))"
        - "x = 10; y = 20; print(x + y)"
        - "def foo(n): return n**2\\nprint(foo(5))"
        - "import numpy as np; print(np.array([1,2,3]).sum())"
        - "import scipy; print(scipy.optimize.fmin(lambda x: x**2, 5))"
        - "import sympy as sp; x = sp.Symbol('x'); print(sp.solve(x**2 - 4, x))"

    Returns:
    --------
    str (JSON format)
        A JSON string containing:

        On Success:
        {
            "interpreter_output": "<str>"
            "session_status": "active"
            "execution_status": "success"
            "error_type": null
        }
        The session remains active and all variables/definitions are preserved for
        subsequent calls.

        On Execution Error (code-level exception):
        {
            "interpreter_output": "<str>"
            "session_status": "active"
            "execution_status": "code_error"
            "error_type": "code_execution_error"
        }
        The session remains active; previously created variables are preserved.

        On Session Error (timeout, crash, resource limit exceeded):
        {
            "interpreter_output": null
            "session_status": "terminated" | "unavailable"
            "execution_status": "session_error"
            "error_type": "code_triggered_session_error" | "session_infrastructure_error"
            "error_message": "<str>"
        }
        The session has been terminated and all resources are freed.
        A new session is created automatically on the next call.
        Note: if code execution times out, the entire session is automatically
        terminated.
    """

    session_id = _require_client_id(ctx)
    session = None

    try:
        session, _ = _get_or_create_session(session_id)
    except Exception as e:
        return _python_exec_session_error(
            error_type="session_infrastructure_error",
            error_message=(
                str(e)
                + " "
                + SESSION_ERROR
            ),
            session_status="unavailable",
        )

    try:
        output = session.execute(code)
        return _python_exec_success(output)
    except CodeExecutionError as e:
        return _python_exec_code_error(str(e))
    except Exception as e:
        message = str(e)
        code_triggered = _is_code_triggered_session_error(message)

        if code_triggered and session is not None:
            session.close()
            with sessions_lock:
                if sessions.get(session_id) is session:
                    sessions.pop(session_id, None)
            return _python_exec_session_error(
                error_type="code_triggered_session_error",
                error_message=(
                    message
                    + " "
                    + SESSION_ERROR
                ),
                session_status="terminated",
            )

        if session is not None and not _session_is_alive(session):
            with sessions_lock:
                if sessions.get(session_id) is session:
                    sessions.pop(session_id, None)

        return _python_exec_session_error(
            error_type="session_infrastructure_error",
            error_message=message,
            session_status="unavailable",
        )
    finally:
        if session is not None and not _session_is_alive(session):
            with sessions_lock:
                if sessions.get(session_id) is session:
                    sessions.pop(session_id, None)


@mcp.tool(tags={"internal"})
def python_create_session(ctx: Context) -> str:
    """
    Create a Python session without executing code.

    This tool explicitly starts a sandboxed Python session for the calling client
    and returns the creation status. Use python_exec() to run code in the same
    stateful session. If a live session already exists for the same client_id, it
    is reused.

    Parameters:
    -----------
    Returns:
    --------
    str (JSON format)

        On Success:
        {
            "session_status": "created"
        }

        On Error:
        {
            "session_status": "error"
            "error_type": "session_infrastructure_error"
            "error_message": "<str>"
        }
    """

    session_id = _require_client_id(ctx)

    try:
        _, created = _get_or_create_session(session_id)
    except Exception as e:
        return json.dumps(
            {
                "session_status": "error",
                "error_type": "session_infrastructure_error",
                "error_message": str(e),
            }
        )

    return json.dumps(
        {
            "session_status": "created" if created else "existing",
        }
    )


@mcp.tool(tags={"internal"})
def python_reset_session(ctx: Context) -> str:
    """
    Terminate and reset a Python session, freeing all resources.

    This tool explicitly closes a Python session and cleans up all associated resources.
    After reset, the session_id cannot be reused and any variables/state are lost.
    Useful for freeing resources or starting fresh without waiting for session timeout.

    Returns:
    --------
    str (JSON format)

        On Success (session existed and was closed):
        {
            "session_status": "reset"
        }

        On Session Not Found:
        {
            "session_status": "not_found"
        }
    """

    session_id = _require_client_id(ctx)

    if _reset_session(session_id):
        return json.dumps({"session_status": "reset"})

    return json.dumps({"session_status": "not_found"})


# -----------------------------
# Entrypoint
# -----------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
