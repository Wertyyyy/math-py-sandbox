import subprocess
import os
import uuid
import json
import threading
import time
import base64
from typing import Dict

from fastmcp import FastMCP


# -----------------------------
# Session management
# -----------------------------


class PythonSession:
    def __init__(
        self,
        session_id: str,
        *,
        nsjail_bin: str,
        host_venv_python: str,
        host_repl_runner: str,
        exec_timeout_seconds: int,
        init_timeout_seconds: int,
        process_time_limit_seconds: int,
    ):
        self.session_id = session_id
        self.nsjail_bin = nsjail_bin
        self.host_venv_python = host_venv_python
        self.host_repl_runner = host_repl_runner
        self.exec_timeout_seconds = exec_timeout_seconds
        self.init_timeout_seconds = init_timeout_seconds
        self.process_time_limit_seconds = process_time_limit_seconds
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
                return response["error"]

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


sessions: Dict[str, PythonSession] = {}


def _active_session_count() -> int:
    return sum(1 for session in sessions.values() if session.proc.poll() is None)


# -----------------------------
# Configuration
# -----------------------------
HOST_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
NSJAIL_BIN = os.path.join(HOST_PROJECT_DIR, "nsjail", "nsjail")
HOST_VENV_PYTHON = os.path.join(HOST_PROJECT_DIR, ".venv", "bin", "python")
EXEC_TIMEOUT_SECONDS = int(os.getenv("EXEC_TIMEOUT_SECONDS", "10"))
INIT_TIMEOUT_SECONDS = int(os.getenv("INIT_TIMEOUT_SECONDS", "20"))
PROCESS_TIME_LIMIT_SECONDS = int(os.getenv("PROCESS_TIME_LIMIT_SECONDS", "600"))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "128"))
HOST_REPL_RUNNER = os.path.join(HOST_PROJECT_DIR, "jail-root", "app", "repl_runner.py")

if not os.path.isfile(NSJAIL_BIN):
    raise FileNotFoundError(f"nsjail binary not found: {NSJAIL_BIN}")

if not os.path.isfile(HOST_VENV_PYTHON):
    raise FileNotFoundError(f"venv python not found: {HOST_VENV_PYTHON}")

if not os.path.isfile(HOST_REPL_RUNNER):
    raise FileNotFoundError(f"repl runner not found: {HOST_REPL_RUNNER}")


# -----------------------------
# MCP Tools
# -----------------------------

mcp = FastMCP("python")


@mcp.tool()
def python_exec(code: str, session_id: str | None = None) -> str:
    """
    This tool runs Python code in an isolated, sandboxed environment using nsjail.
    Multiple code executions can be performed in the same session, preserving variables
    and state between calls. Each session has strict time and resource limits for security.

    The execution environment includes numpy, scipy, and sympy. No other third-party
    libraries are available.

    Parameters:
    -----------
    code : str
        Python code to execute as a string. Can include multiple lines, imports,
        function definitions, loops, etc. Any print output is captured and returned.
        Please import any required libraries (e.g. numpy, scipy, sympy)
        within the code string.

        Examples of valid code:
        - "print('hello')"
        - "import math; print(math.sqrt(16))"
        - "x = 10; y = 20; print(x + y)"
        - "def foo(n): return n**2\\nprint(foo(5))"
        - "import numpy as np; print(np.array([1,2,3]).sum())"
        - "import scipy; print(scipy.optimize.fmin(lambda x: x**2, 5))"
        - "import sympy as sp; x = sp.Symbol('x'); print(sp.solve(x**2 - 4, x))"

    session_id : str | None, optional
        A unique identifier for the Python session. If None, a new UUID is automatically
        generated and a fresh session is created. All subsequent calls with the same
        session_id execute in the same session context, preserving variables, imports,
        and function definitions. Default is None (creates a new session).

        Best practices:
        - Reuse session_id to maintain state across multiple executions
        - Store session_id for later use if you need to execute more code in the same context
        - Pass None to create separate isolated sessions when needed

    Returns:
    --------
    str (JSON format)
        A JSON string containing:

        On Success:
        {
            "session_id": "<str>",      # The session ID (new or provided)
            "output": "<str>"           # The captured stdout from code execution
        }
        The session remains active and all variables/definitions are preserved for
        subsequent calls using the same session_id.

        On Execution Error (code-level exception):
        {
            "session_id": "<str>",
            "output": "<str>"           # Traceback and error message
        }
        The session remains active; previously created variables are preserved and
        you can continue using this session_id.

        On Session Error (timeout, crash, resource limit exceeded):
        {
            "session_id": "<str>",
            "error": "<str>"            # Error description (session terminated)
        }
        The session has been terminated and all resources are freed. The session_id
        cannot be reused. If you need to continue, pass session_id=None to create
        a new session. Note: if code execution times out, the entire session is
        automatically terminated.
    """

    if session_id is None:
        session_id = str(uuid.uuid4())

    if session_id not in sessions:
        if _active_session_count() >= MAX_SESSIONS:
            return json.dumps(
                {
                    "session_id": session_id,
                    "error": f"Maximum active session limit reached ({MAX_SESSIONS}). Please reset an existing session before creating a new one.",
                }
            )

        sessions[session_id] = PythonSession(
            session_id,
            nsjail_bin=NSJAIL_BIN,
            host_venv_python=HOST_VENV_PYTHON,
            host_repl_runner=HOST_REPL_RUNNER,
            exec_timeout_seconds=EXEC_TIMEOUT_SECONDS,
            init_timeout_seconds=INIT_TIMEOUT_SECONDS,
            process_time_limit_seconds=PROCESS_TIME_LIMIT_SECONDS,
        )

    session = sessions[session_id]

    try:
        output = session.execute(code)
        return json.dumps(
            {
                "session_id": session_id,
                "output": output,
            }
        )
    except Exception as e:
        return json.dumps(
            {
                "session_id": session_id,
                "error": str(e),
            }
        )


@mcp.tool()
def python_reset(session_id: str) -> str:
    """
    Terminate and reset a Python session, freeing all resources.

    This tool explicitly closes a Python session and cleans up all associated resources.
    After reset, the session_id cannot be reused and any variables/state are lost.
    Useful for freeing resources or starting fresh without waiting for session timeout.

    Parameters:
    -----------
    session_id : str
        The unique identifier of the session to reset. Must be a valid session_id that
        was previously created by python_exec(). Attempting to reset a non-existent
        session returns "not_found" status without error.

    Returns:
    --------
    str (JSON format)

        On Success (session existed and was closed):
        {
            "status": "reset"
        }

        On Session Not Found:
        {
            "status": "not_found"
        }
    """

    if session_id in sessions:
        sessions[session_id].close()
        del sessions[session_id]
        return json.dumps({"status": "reset"})

    return json.dumps({"status": "not_found"})


# -----------------------------
# Entrypoint
# -----------------------------

if __name__ == "__main__":
    mcp.run()
