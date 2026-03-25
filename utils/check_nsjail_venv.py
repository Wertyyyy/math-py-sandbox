#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "4")


PROJECT_DIR = Path(__file__).resolve().parent.parent
NSJAIL_BIN = PROJECT_DIR / "nsjail" / "nsjail"
HOST_VENV_PYTHON = PROJECT_DIR / ".venv" / "bin" / "python"
JAIL_ROOT_DIR = PROJECT_DIR / "jail-root"
JAIL_VENV_PYTHON = JAIL_ROOT_DIR / "venv" / ".venv" / "bin" / "python"
JAIL_REPL_RUNNER = JAIL_ROOT_DIR / "app" / "repl_runner.py"


CLONE_SWITCHES = [
    "--disable_clone_newuser",
    "--disable_clone_newnet",
    "--disable_clone_newns",
    "--disable_clone_newpid",
    "--disable_clone_newipc",
    "--disable_clone_newuts",
    "--disable_clone_newcgroup",
]


THREAD_ENV_VARS = [
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
]


def bind_mount_args() -> list[str]:
    bind_paths = [
        "/lib/x86_64-linux-gnu",
        "/lib64",
        "/usr/lib/x86_64-linux-gnu",
        "/usr/lib64",
    ]

    args: list[str] = []
    for path in bind_paths:
        if os.path.isdir(path):
            args.extend(["--bindmount_ro", path])

    return args


PYTHON_SMOKE_CODE = "import numpy, scipy, sympy; print('python-import-ok')"


def run_process(command: list[str], *, input_text: str | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        command,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def nsjail_command(extra_args: list[str], python_path: str, code: str) -> list[str]:
    return [
        str(NSJAIL_BIN),
        "--quiet",
        "--time_limit",
        "10",
        "--keep_env",
        *[item for name in THREAD_ENV_VARS for item in ("--env", name)],
        *extra_args,
        "--",
        python_path,
        "-c",
        code,
    ]


def print_result(title: str, ok: bool, stdout: str, stderr: str) -> None:
    print(title)
    print(f"  result: {'PASS' if ok else 'FAIL'}")
    if stdout:
        print(f"  stdout: {stdout}")
    if stderr:
        print(f"  stderr: {stderr}")
    print()


def probe_direct_venv() -> bool:
    rc, stdout, stderr = run_process([str(HOST_VENV_PYTHON), "-c", PYTHON_SMOKE_CODE])
    ok = rc == 0 and "python-import-ok" in stdout
    print_result("direct venv python", ok, stdout, stderr)
    return ok


def probe_nsjail_host_venv() -> bool:
    command = nsjail_command(CLONE_SWITCHES, str(HOST_VENV_PYTHON), PYTHON_SMOKE_CODE)
    rc, stdout, stderr = run_process(command)
    ok = rc == 0 and "python-import-ok" in stdout
    print_result("nsjail + host venv python", ok, stdout, stderr)
    return ok


def probe_nsjail_jail_root() -> bool:
    command = [
        str(NSJAIL_BIN),
        "--quiet",
        "--keep_env",
        *[item for name in THREAD_ENV_VARS for item in ("--env", name)],
        "--chroot",
        str(JAIL_ROOT_DIR),
        "--cwd",
        "/tmp",
        *bind_mount_args(),
        "--time_limit",
        "10",
        *CLONE_SWITCHES,
        "--",
        "/venv/.venv/bin/python",
        "-c",
        PYTHON_SMOKE_CODE,
    ]
    rc, stdout, stderr = run_process(command)
    ok = rc == 0 and "python-import-ok" in stdout
    print_result("nsjail + jail-root chroot", ok, stdout, stderr)
    return ok


def show_layout_info() -> None:
    print(f"project dir: {PROJECT_DIR}")
    print(f"nsjail binary: {NSJAIL_BIN}")
    print(f"host venv python: {HOST_VENV_PYTHON}")
    print(f"jail root: {JAIL_ROOT_DIR}")
    print(f"jail venv python: {JAIL_VENV_PYTHON}")
    print(f"jail repl runner: {JAIL_REPL_RUNNER}")

    if JAIL_VENV_PYTHON.exists():
        print(f"jail venv python is_symlink: {JAIL_VENV_PYTHON.is_symlink()}")
        if JAIL_VENV_PYTHON.is_symlink():
            try:
                target = JAIL_VENV_PYTHON.resolve(strict=False)
                print(f"jail venv python target: {target}")
                try:
                    target.relative_to(JAIL_ROOT_DIR)
                except ValueError:
                    print(
                        "jail venv python warning: symlink target is outside jail-root; chroot mode will not be able to execute it unless the target is copied or bind-mounted into the jail"
                    )
            except OSError as exc:
                print(f"jail venv python target: <unresolved> ({exc})")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe whether nsjail and the virtual environment work in this workspace."
    )
    parser.add_argument(
        "--only",
        choices=("direct", "host", "chroot", "all"),
        default="all",
        help="Limit which probes are executed.",
    )
    args = parser.parse_args()

    missing = [
        path
        for path in (NSJAIL_BIN, HOST_VENV_PYTHON, JAIL_ROOT_DIR, JAIL_REPL_RUNNER)
        if not path.exists()
    ]
    if missing:
        print("Missing required path(s):", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        return 2

    show_layout_info()

    results: list[bool] = []
    if args.only in ("direct", "all"):
        results.append(probe_direct_venv())
    if args.only in ("host", "all"):
        results.append(probe_nsjail_host_venv())
    if args.only in ("chroot", "all"):
        results.append(probe_nsjail_jail_root())

    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
