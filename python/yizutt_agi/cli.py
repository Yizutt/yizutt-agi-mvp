import argparse
import json
import os
import sys
from pathlib import Path

from . import skill_market


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return start_main([])
    if args[0] in {"-h", "--help"}:
        print_main_help()
        return 0
    if args[0] == "start":
        return start_main(args[1:])
    if args[0] == "skill":
        return skill_market.main(args)

    return start_main(args)


def print_main_help() -> None:
    print(
        """usage: yizutt [start] [options]
       yizutt skill <install|list> ...

Run without a subcommand to start the local Yizutt Runtime and Web workbench.

Commands:
  start      Start the local mock model, Runtime, and Web workbench.
  skill      Manage skill packages.

Common start options:
  --panel-port PORT
  --runtime-port PORT
  --mock-port PORT
  --no-build
  --project-root PATH
  --dry-run
"""
    )


def start_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yizutt start",
        description="Start the local Yizutt Runtime and Web workbench.",
    )
    parser.add_argument("--project-root", default=os.getenv("YIZUTT_PROJECT_ROOT", ""))
    parser.add_argument("--panel-port")
    parser.add_argument("--runtime-host")
    parser.add_argument("--runtime-port")
    parser.add_argument("--worker-base-port")
    parser.add_argument("--mock-port")
    parser.add_argument("--min-workers")
    parser.add_argument("--max-workers")
    parser.add_argument("--runtime-home")
    parser.add_argument("--panel-history")
    parser.add_argument("--log-dir")
    parser.add_argument("--runtime-bin")
    parser.add_argument("--recovery-mode", choices=["none", "resume", "expire"])
    build = parser.add_mutually_exclusive_group()
    build.add_argument("--build", action="store_true", help="Build the Rust workspace before startup.")
    build.add_argument("--no-build", action="store_true", help="Skip the Rust build step.")
    parser.add_argument("--dry-run", action="store_true", help="Print the resolved startup command without running it.")
    args = parser.parse_args(argv)

    project_root = resolve_project_root(args.project_root)
    script = project_root / "scripts" / "start_local_demo.sh"
    if not script.exists():
        raise SystemExit(f"startup script not found: {script}")

    env = os.environ.copy()
    env["YIZUTT_PROJECT_ROOT"] = str(project_root)
    copy_option(env, "PANEL_PORT", args.panel_port)
    copy_option(env, "RUNTIME_HOST", args.runtime_host)
    copy_option(env, "RUNTIME_PORT", args.runtime_port)
    copy_option(env, "WORKER_BASE_PORT", args.worker_base_port)
    copy_option(env, "MOCK_PORT", args.mock_port)
    copy_option(env, "MIN_WORKERS", args.min_workers)
    copy_option(env, "MAX_WORKERS", args.max_workers)
    copy_option(env, "RUNTIME_HOME", args.runtime_home)
    copy_option(env, "PANEL_HISTORY", args.panel_history)
    copy_option(env, "LOG_DIR", args.log_dir)
    copy_option(env, "RUNTIME_BIN", args.runtime_bin)
    copy_option(env, "RECOVERY_MODE", args.recovery_mode)
    if args.build:
        env["BUILD"] = "1"
    if args.no_build:
        env["BUILD"] = "0"

    command = ["bash", str(script)]
    if args.dry_run:
        print(json.dumps({
            "ok": True,
            "cwd": str(project_root),
            "command": command,
            "env": exported_start_env(env),
        }, ensure_ascii=False, indent=2))
        return 0

    os.chdir(project_root)
    os.execvpe(command[0], command, env)
    return 127


def resolve_project_root(value: str) -> Path:
    candidates: list[Path] = []
    if value:
        candidates.append(Path(value).expanduser().resolve())
    here = Path(__file__).resolve()
    candidates.extend([Path.cwd().resolve(), *here.parents])
    for candidate in candidates:
        if (candidate / "pyproject.toml").exists() and (candidate / "scripts" / "start_local_demo.sh").exists():
            return candidate
    raise SystemExit("cannot find Yizutt project root; set YIZUTT_PROJECT_ROOT=/path/to/repo")


def copy_option(env: dict[str, str], name: str, value: str | None) -> None:
    if value:
        env[name] = value


def exported_start_env(env: dict[str, str]) -> dict[str, str]:
    names = [
        "YIZUTT_PROJECT_ROOT",
        "PANEL_PORT",
        "RUNTIME_HOST",
        "RUNTIME_PORT",
        "WORKER_BASE_PORT",
        "MOCK_PORT",
        "MIN_WORKERS",
        "MAX_WORKERS",
        "RUNTIME_HOME",
        "PANEL_HISTORY",
        "LOG_DIR",
        "RUNTIME_BIN",
        "RECOVERY_MODE",
        "BUILD",
    ]
    return {name: env[name] for name in names if name in env}


if __name__ == "__main__":
    raise SystemExit(main())
