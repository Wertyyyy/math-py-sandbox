# Sandbox Status

This repository contains a Python sandbox service built on MCP. It is used to validate `server.py`, `nsjail`, and the pytest integration tests around them.

## Project Overview

- `server.py` exposes the MCP tools used to execute Python code in isolated sessions
- `tests/` contains end-to-end pytest coverage for session behavior, timeouts, limits, and workflow scenarios
- `check_nsjail_venv.py` is a probe script for checking nsjail and virtual environment behavior in this workspace
- `jail-root/` is the working directory for chroot and rootfs experiments
- `nsjail/` contains the nsjail source tree and binary used by the sandbox

## MCP Tools

The MCP server currently exposes three tools. Each tool returns a JSON string.

### `python_exec`

Executes Python code inside the sandboxed, stateful interpreter session for the calling `client_id`.

- Success:
	- `execution_status: "success"`
	- `session_status: "active"`
	- `error_type: null`
	- `error_message: null`
	- `interpreter_output`: captured stdout from the executed code
- Failure: code-level exception
	- `execution_status: "code_error"`
	- `session_status: "active"`
	- `error_type: "code_execution_error"`
	- `error_message`: human-readable code execution error message
	- `interpreter_output`: traceback text from the executed code
- Failure: session timeout, nsjail kill, or child process crash
	- `execution_status: "session_error"`
	- `session_status: "terminated"` or `"unavailable"`
	- `error_type: "code_triggered_session_error"` or `"session_infrastructure_error"`
	- `error_message`: reason the session became unusable
	- `interpreter_output: null`

### `python_create_session`

Creates the sandboxed interpreter session without executing code.

- Success:
	- `session_status: "created"` when a new session is started
	- `session_status: "existing"` when an active session already exists for the same `client_id`
- Failure:
	- `session_status: "error"`
	- `error_type: "session_infrastructure_error"`
	- `error_message`: reason the session could not be created

### `python_reset_session`

Terminates and removes the sandboxed interpreter session for the calling `client_id`.

- Success:
	- `session_status: "reset"`
- Failure:
	- `session_status: "not_found"` when no session exists for that `client_id`

### Common response fields

- `execution_status`: overall execution result for `python_exec`
- `session_status`: lifecycle state of the sandboxed session
- `error_type`: machine-readable error category when applicable
- `error_message`: detailed explanation when applicable
- `interpreter_output`: stdout or traceback text from the sandboxed interpreter

## Current Progress

- `server.py` is in a runnable state
- The existing pytest integration suite passes
- The `host venv + nsjail` execution path works in the current container
- The `jail-root + chroot` path still does not work in the current Docker environment

## Known Issues

- nsjail fails to build the mount tree in this container with `mount('/', MS_REC|MS_PRIVATE): Permission denied`
- The Python entry in `jail-root` is no longer a symlink, but chroot execution still fails, which indicates the rootfs is incomplete
- A full `--chroot jail-root` setup is not stable in the current environment, especially for bind mounts and deeper isolation

## Test Commands

- Run all tests: `uv run -m pytest -q tests`
- Run nsjail switches probe: `uv run utils/check_nsjail_switches.py`
- Run the environment probe: `uv run utils/check_nsjail_venv.py`
