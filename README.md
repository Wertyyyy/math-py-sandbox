# Sandbox Status

This repository contains a Python sandbox service built on MCP. It is used to validate `server.py`, `nsjail`, and the pytest integration tests around them.

## Project Overview

- `server.py` exposes the MCP tools used to execute Python code in isolated sessions
- `tests/` contains end-to-end pytest coverage for session behavior, timeouts, limits, and workflow scenarios
- `check_nsjail_venv.py` is a probe script for checking nsjail and virtual environment behavior in this workspace
- `jail-root/` is the working directory for chroot and rootfs experiments
- `nsjail/` contains the nsjail source tree and binary used by the sandbox

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
