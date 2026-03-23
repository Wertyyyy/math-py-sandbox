#!/usr/bin/env python3

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
NSJAIL_BIN = PROJECT_DIR / "nsjail" / "nsjail"


CLONE_SWITCHES = [
    "--disable_clone_newuser",
    "--disable_clone_newnet",
    "--disable_clone_newns",
    "--disable_clone_newpid",
    "--disable_clone_newipc",
    "--disable_clone_newuts",
    "--disable_clone_newcgroup",
]


def build_command(enabled_switches: list[str]) -> list[str]:
    return [
        str(NSJAIL_BIN),
        "--quiet",
        "--time_limit",
        "10",
        *enabled_switches,
        "--",
        "/bin/sh",
        "-lc",
        "echo nsjail-probe-ok",
    ]


def run_probe(enabled_switches: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(
        build_command(enabled_switches),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    success = proc.returncode == 0 and "nsjail-probe-ok" in proc.stdout
    details = (proc.stdout + proc.stderr).strip()
    return success, details


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe which nsjail clone-related switches can be enabled in this environment."
    )
    parser.add_argument(
        "--keep-all-disabled",
        action="store_true",
        help="Only run the baseline command with all clone switches disabled.",
    )
    args = parser.parse_args()

    if not NSJAIL_BIN.exists():
        print(f"nsjail binary not found: {NSJAIL_BIN}", file=sys.stderr)
        return 2

    print(f"nsjail binary: {NSJAIL_BIN}")
    print(f"project dir: {PROJECT_DIR}")
    print()

    baseline_success, baseline_details = run_probe(CLONE_SWITCHES)
    print("baseline: all clone switches disabled")
    print(f"  result: {'PASS' if baseline_success else 'FAIL'}")
    if baseline_details:
        print(f"  details: {baseline_details}")
    print()

    if args.keep_all_disabled:
        return 0 if baseline_success else 1

    any_failure = False
    for switch in CLONE_SWITCHES:
        enabled_switches = [flag for flag in CLONE_SWITCHES if flag != switch]
        success, details = run_probe(enabled_switches)
        any_failure = any_failure or (not success)
        print(f"probe: without {switch}")
        print(f"  result: {'PASS' if success else 'FAIL'}")
        if details:
            print(f"  details: {details}")
        print()

    return 1 if any_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
