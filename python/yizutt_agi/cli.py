import argparse
import json
import os
import sys
from pathlib import Path

from .model_gateway import ModelGateway
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
    if args[0] == "onboard":
        return onboard_main(args[1:])
    if args[0] == "gateway":
        return gateway_main(args[1:])
    if args[0] == "skill":
        return skill_market.main(args)

    return start_main(args)


def print_main_help() -> None:
    print(
        """usage: yizutt [startup options]
       yizutt <command> [options]

Run without a subcommand to start the local Yizutt Runtime and Web workbench.

Commands:
  onboard   Show first-run paths, checks, and next commands.
  gateway   Inspect model gateway provider configuration.
  skill     Manage skill packages.
  start     Compatibility alias for the default startup.

Examples:
  yizutt
  yizutt --no-build
  yizutt onboard
  yizutt gateway
  yizutt gateway status --json
  yizutt skill <install|list> ...

Startup options:
  --panel-port PORT
  --runtime-port PORT
  --mock-port PORT
  --no-build
  --project-root PATH
  --dry-run
"""
    )


def onboard_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yizutt onboard",
        description="Show first-run Yizutt paths, checks, and next commands.",
    )
    parser.add_argument("--project-root", default=os.getenv("YIZUTT_PROJECT_ROOT", ""))
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    project_root = resolve_project_root(args.project_root)
    panel_port = os.getenv("PANEL_PORT", "50280")
    runtime_port = os.getenv("RUNTIME_PORT", "50200")
    runtime_bin = resolve_runtime_bin(project_root, os.getenv("RUNTIME_BIN", "target/debug/yizutt-runtime"))
    report = {
        "ok": True,
        "project_root": str(project_root),
        "python": sys.executable,
        "runtime": {
            "addr": f"http://127.0.0.1:{runtime_port}",
            "binary": str(runtime_bin),
            "binary_exists": Path(runtime_bin).exists(),
            "home": str(project_root / ".yizutt" / "runtime"),
        },
        "workbench": {
            "url": f"http://127.0.0.1:{panel_port}",
            "history": str(project_root / ".yizutt" / "panel" / "history.sqlite3"),
        },
        "data": {
            "memory": str(project_root / ".yizutt" / "memory" / "work.sqlite3"),
            "skills": str(project_root / ".yizutt" / "skills"),
            "logs": str(project_root / ".yizutt" / "local-demo" / "logs"),
        },
        "gateway": gateway_status_payload(),
        "commands": [
            "yizutt",
            "yizutt --no-build",
            "yizutt gateway",
            "yizutt skill list",
        ],
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_onboard(report)
    return 0


def gateway_main(argv: list[str]) -> int:
    if argv and argv[0] == "status":
        argv = argv[1:]
    parser = argparse.ArgumentParser(
        prog="yizutt gateway",
        description="Inspect model gateway provider configuration without printing secrets.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    payload = gateway_status_payload()
    if args.json:
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
    else:
        print_gateway_status(payload)
    return 0


def print_onboard(report: dict[str, object]) -> None:
    runtime = report["runtime"]
    workbench = report["workbench"]
    data = report["data"]
    assert isinstance(runtime, dict)
    assert isinstance(workbench, dict)
    assert isinstance(data, dict)
    print("Yizutt onboarding")
    print(f"Project:   {report['project_root']}")
    print(f"Python:    {report['python']}")
    print(f"Runtime:   {runtime['addr']}")
    print(f"Workbench: {workbench['url']}")
    print(f"Logs:      {data['logs']}")
    print("")
    print("Checks:")
    runtime_state = "ok" if runtime["binary_exists"] else "missing, run yizutt once to build it"
    print(f"  runtime binary: {runtime_state}")
    print(f"  gateway:        {gateway_summary(report['gateway'])}")
    print("")
    print("Next commands:")
    for command in report["commands"]:
        print(f"  {command}")


def print_gateway_status(payload: dict[str, object]) -> None:
    print("Yizutt model gateway")
    print(f"Default provider: {payload['default_provider'] or 'not configured'}")
    print("")
    providers = payload["providers"]
    assert isinstance(providers, dict)
    for name in ["openai", "anthropic", "local"]:
        item = providers[name]
        assert isinstance(item, dict)
        state = "configured" if item["configured"] else "missing"
        detail = item.get("model") or item.get("url") or item.get("base_url") or ""
        print(f"  {name}: {state}{f' ({detail})' if detail else ''}")
    print("")
    print("Set one of: OPENAI_API_KEY, ANTHROPIC_API_KEY, YIZUTT_LOCAL_MODEL_URL")


def gateway_status_payload() -> dict[str, object]:
    gateway = ModelGateway()
    openai_key = bool(os.getenv("OPENAI_API_KEY") or (gateway.openai_base_url != "https://api.openai.com/v1" and os.getenv("PROXY_API_KEY")))
    anthropic_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    local_url = bool(gateway.local_url)
    default_provider = ""
    for name, configured in [("openai", openai_key), ("anthropic", anthropic_key), ("local", local_url)]:
        if configured:
            default_provider = name
            break
    return {
        "default_provider": default_provider,
        "providers": {
            "openai": {
                "configured": openai_key,
                "model": gateway.openai_model,
                "base_url": gateway.openai_base_url,
                "api_style": gateway.openai_api_style,
                "auth": "OPENAI_API_KEY" if os.getenv("OPENAI_API_KEY") else ("PROXY_API_KEY" if openai_key else ""),
            },
            "anthropic": {
                "configured": anthropic_key,
                "model": gateway.anthropic_model,
                "auth": "ANTHROPIC_API_KEY" if anthropic_key else "",
            },
            "local": {
                "configured": local_url,
                "url": gateway.local_url,
                "auth": "",
            },
        },
    }


def gateway_summary(value: object) -> str:
    if not isinstance(value, dict):
        return "unknown"
    provider = value.get("default_provider")
    return str(provider) if provider else "no provider configured"


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


def resolve_runtime_bin(project_root: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate


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
