import argparse
import json
import os
import sys
from pathlib import Path

from . import skill_market


CONFIG_VERSION = 1
DEFAULT_CONFIG_REL = ".yizutt/config.json"
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
PRODUCT_PILLARS = [
    {
        "name": "codex",
        "focus": "agent function and execution logic",
        "description": "planner, tool loop, runtime actions, sandbox policy, traces, and task handoff semantics.",
    },
    {
        "name": "openclaw",
        "focus": "web and command surface",
        "description": "global yizutt command, setup/onboard/gateway flows, and the browser operator workbench.",
    },
    {
        "name": "hermes",
        "focus": "memory and learning",
        "description": "durable memory, retrieval, skill learning, training buffers, and future LoRA workflows.",
    },
]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return start_main([])
    if args[0] in {"-h", "--help"}:
        print_main_help()
        return 0
    if args[0] == "start":
        return start_main(args[1:])
    if args[0] == "setup":
        return setup_main(args[1:])
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
  setup     Initialize .yizutt/config.json with a guided setup.
  onboard   Show first-run paths, checks, and next commands.
  gateway   Inspect model gateway provider configuration.
  skill     Manage skill packages.
  start     Compatibility alias for the default startup.

Product shape:
  Codex-style agent core, OpenClaw-style web/commands, Hermes-style memory/learning.

Examples:
  yizutt
  yizutt setup
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


def setup_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yizutt setup",
        description="Initialize guided Yizutt local configuration.",
    )
    parser.add_argument("--project-root", default=os.getenv("YIZUTT_PROJECT_ROOT", ""))
    parser.add_argument("--config", default=os.getenv("YIZUTT_CONFIG_PATH", ""))
    parser.add_argument("--yes", action="store_true", help="Use defaults and do not prompt.")
    parser.add_argument("--dry-run", action="store_true", help="Print the config that would be written.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    project_root = resolve_project_root(args.project_root)
    existing, path = load_config(project_root, args.config)
    config = merge_dict(default_setup_config(project_root), existing)
    if args.yes:
        config = normalize_setup_config(config)
    else:
        if not sys.stdin.isatty():
            raise SystemExit("interactive setup needs a TTY; use yizutt setup --yes for defaults")
        config = prompt_setup_config(config, path)

    payload = {"ok": True, "path": str(path), "config": config}
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("Yizutt setup complete")
        print(f"Config: {path}")
        print("")
        print("Next commands:")
        print("  yizutt gateway")
        print("  yizutt onboard")
        print("  yizutt")
    return 0


def onboard_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yizutt onboard",
        description="Show first-run Yizutt paths, checks, and next commands.",
    )
    parser.add_argument("--project-root", default=os.getenv("YIZUTT_PROJECT_ROOT", ""))
    parser.add_argument("--config", default=os.getenv("YIZUTT_CONFIG_PATH", ""))
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    project_root = resolve_project_root(args.project_root)
    config, config_path = load_config(project_root, args.config)
    env = configured_env(project_root, config, config_path)
    panel_port = env.get("PANEL_PORT", "50280")
    runtime_port = env.get("RUNTIME_PORT", "50200")
    runtime_bin = resolve_runtime_bin(project_root, env.get("RUNTIME_BIN", "target/debug/yizutt-runtime"))
    report = {
        "ok": True,
        "project_root": str(project_root),
        "config": {
            "path": str(config_path),
            "exists": config_path.exists(),
        },
        "product_pillars": PRODUCT_PILLARS,
        "python": sys.executable,
        "runtime": {
            "addr": f"http://{env.get('RUNTIME_HOST', '127.0.0.1')}:{runtime_port}",
            "binary": str(runtime_bin),
            "binary_exists": Path(runtime_bin).exists(),
            "home": env.get("RUNTIME_HOME", str(project_root / ".yizutt" / "runtime")),
        },
        "workbench": {
            "url": f"http://127.0.0.1:{panel_port}",
            "history": env.get("PANEL_HISTORY", str(project_root / ".yizutt" / "panel" / "history.sqlite3")),
        },
        "data": {
            "memory": env.get("YIZUTT_MEMORY_PATH", str(project_root / ".yizutt" / "memory" / "work.sqlite3")),
            "skills": env.get("YIZUTT_SKILLS_ROOT", str(project_root / ".yizutt" / "skills")),
            "logs": env.get("LOG_DIR", str(project_root / ".yizutt" / "local-demo" / "logs")),
        },
        "gateway": gateway_status_payload(env),
        "commands": [
            "yizutt setup",
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
    parser.add_argument("--project-root", default=os.getenv("YIZUTT_PROJECT_ROOT", ""))
    parser.add_argument("--config", default=os.getenv("YIZUTT_CONFIG_PATH", ""))
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    project_root = resolve_project_root(args.project_root)
    config, config_path = load_config(project_root, args.config)
    env = configured_env(project_root, config, config_path)
    payload = gateway_status_payload(env)
    payload["config"] = {"path": str(config_path), "exists": config_path.exists()}
    if args.json:
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
    else:
        print_gateway_status(payload)
    return 0


def print_onboard(report: dict[str, object]) -> None:
    config = report["config"]
    product_pillars = report["product_pillars"]
    runtime = report["runtime"]
    workbench = report["workbench"]
    data = report["data"]
    assert isinstance(config, dict)
    assert isinstance(product_pillars, list)
    assert isinstance(runtime, dict)
    assert isinstance(workbench, dict)
    assert isinstance(data, dict)
    print("Yizutt onboarding")
    print(f"Project:   {report['project_root']}")
    print(f"Config:    {config['path']}{'' if config['exists'] else ' (not initialized)'}")
    print(f"Python:    {report['python']}")
    print(f"Runtime:   {runtime['addr']}")
    print(f"Workbench: {workbench['url']}")
    print(f"Logs:      {data['logs']}")
    print("")
    print("Product pillars:")
    for item in product_pillars:
        assert isinstance(item, dict)
        print(f"  {item['name']}: {item['focus']}")
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
    config = payload.get("config")
    print("Yizutt model gateway")
    print(f"Default provider: {payload['default_provider'] or 'not configured'}")
    if isinstance(config, dict):
        print(f"Config: {config['path']}{'' if config['exists'] else ' (not initialized)'}")
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


def gateway_status_payload(env: dict[str, str] | None = None) -> dict[str, object]:
    values = os.environ if env is None else env
    openai_model = values.get("YIZUTT_OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    anthropic_model = values.get("YIZUTT_ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)
    openai_base_url = values.get("YIZUTT_OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL).rstrip("/")
    openai_api_style = values.get("YIZUTT_OPENAI_API_STYLE") or (
        "responses" if openai_base_url == DEFAULT_OPENAI_BASE_URL else "chat"
    )
    local_url = values.get("YIZUTT_LOCAL_MODEL_URL", "")
    openai_key = bool(values.get("OPENAI_API_KEY") or (openai_base_url != DEFAULT_OPENAI_BASE_URL and values.get("PROXY_API_KEY")))
    anthropic_key = bool(values.get("ANTHROPIC_API_KEY"))
    local_configured = bool(local_url)
    providers = {
        "openai": openai_key,
        "anthropic": anthropic_key,
        "local": local_configured,
    }
    preferred = values.get("YIZUTT_MODEL_PROVIDER", "")
    if preferred in providers and providers[preferred]:
        default_provider = preferred
    else:
        default_provider = ""
        for name, configured in providers.items():
            if configured:
                default_provider = name
                break
    return {
        "default_provider": default_provider,
        "providers": {
            "openai": {
                "configured": openai_key,
                "model": openai_model,
                "base_url": openai_base_url,
                "api_style": openai_api_style,
                "auth": "OPENAI_API_KEY" if values.get("OPENAI_API_KEY") else ("PROXY_API_KEY" if openai_key else ""),
            },
            "anthropic": {
                "configured": anthropic_key,
                "model": anthropic_model,
                "auth": "ANTHROPIC_API_KEY" if anthropic_key else "",
            },
            "local": {
                "configured": local_configured,
                "url": local_url,
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
    parser.add_argument("--config", default=os.getenv("YIZUTT_CONFIG_PATH", ""))
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
    config, config_path = load_config(project_root, args.config)
    script = project_root / "scripts" / "start_local_demo.sh"
    if not script.exists():
        raise SystemExit(f"startup script not found: {script}")

    env = configured_env(project_root, config, config_path)
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


def config_path_for(project_root: Path, value: str = "") -> Path:
    candidate = Path(value or DEFAULT_CONFIG_REL).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate


def load_config(project_root: Path, value: str = "") -> tuple[dict[str, object], Path]:
    path = config_path_for(project_root, value)
    if not path.exists():
        return {}, path
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"config must be a JSON object: {path}")
    return data, path


def configured_env(project_root: Path, config: dict[str, object], config_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["YIZUTT_PROJECT_ROOT"] = str(project_root)
    env["YIZUTT_CONFIG_PATH"] = str(config_path)
    apply_config_defaults(env, config)
    return env


def apply_config_defaults(env: dict[str, str], config: dict[str, object]) -> None:
    runtime = child_dict(config, "runtime")
    panel = child_dict(config, "panel")
    model = child_dict(config, "model")
    paths = child_dict(config, "paths")
    startup = child_dict(config, "startup")

    set_default(env, "RUNTIME_HOST", runtime.get("host"))
    set_default(env, "RUNTIME_PORT", runtime.get("port"))
    set_default(env, "WORKER_BASE_PORT", runtime.get("worker_base_port"))
    set_default(env, "MOCK_PORT", runtime.get("mock_port"))
    set_default(env, "MIN_WORKERS", runtime.get("min_workers"))
    set_default(env, "MAX_WORKERS", runtime.get("max_workers"))
    set_default(env, "RUNTIME_HOME", runtime.get("home"))
    set_default(env, "RECOVERY_MODE", runtime.get("recovery_mode"))

    set_default(env, "PANEL_PORT", panel.get("port"))
    set_default(env, "PANEL_HISTORY", panel.get("history_path"))

    set_default(env, "LOG_DIR", paths.get("log_dir"))
    set_default(env, "YIZUTT_MEMORY_PATH", paths.get("memory_path"))
    set_default(env, "YIZUTT_SKILLS_ROOT", paths.get("skills_root"))

    if "build" in startup and "BUILD" not in env:
        env["BUILD"] = "1" if bool(startup["build"]) else "0"

    set_default(env, "YIZUTT_MODEL_PROVIDER", model.get("provider"))
    set_default(env, "YIZUTT_OPENAI_MODEL", model.get("openai_model"))
    set_default(env, "YIZUTT_OPENAI_BASE_URL", model.get("openai_base_url"))
    set_default(env, "YIZUTT_OPENAI_API_STYLE", model.get("openai_api_style"))
    set_default(env, "YIZUTT_ANTHROPIC_MODEL", model.get("anthropic_model"))
    if model.get("provider") == "local" or model.get("local_model_url"):
        set_default(env, "YIZUTT_LOCAL_MODEL_URL", model.get("local_model_url"))


def set_default(env: dict[str, str], name: str, value: object) -> None:
    if value is None or value == "" or name in env:
        return
    env[name] = str(value)


def child_dict(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def default_setup_config(project_root: Path) -> dict[str, object]:
    return {
        "version": CONFIG_VERSION,
        "runtime": {
            "host": "127.0.0.1",
            "port": 50200,
            "worker_base_port": 50210,
            "mock_port": 50990,
            "min_workers": 1,
            "max_workers": 2,
            "home": ".yizutt/runtime",
            "recovery_mode": "none",
        },
        "panel": {
            "port": 50280,
            "history_path": ".yizutt/panel/history.sqlite3",
        },
        "model": {
            "provider": "local",
            "local_model_url": "http://127.0.0.1:50990",
            "openai_model": DEFAULT_OPENAI_MODEL,
            "openai_base_url": DEFAULT_OPENAI_BASE_URL,
            "openai_api_style": "responses",
            "anthropic_model": DEFAULT_ANTHROPIC_MODEL,
            "required_env": [],
        },
        "paths": {
            "log_dir": ".yizutt/local-demo/logs",
            "memory_path": ".yizutt/memory/work.sqlite3",
            "skills_root": ".yizutt/skills",
        },
        "startup": {
            "build": True,
        },
    }


def normalize_setup_config(config: dict[str, object]) -> dict[str, object]:
    runtime = child_dict(config, "runtime")
    model = child_dict(config, "model")
    provider = str(model.get("provider") or "local")
    if provider == "local" and not model.get("local_model_url"):
        model["local_model_url"] = f"http://127.0.0.1:{runtime.get('mock_port', 50990)}"
    if provider == "openai":
        model["required_env"] = ["OPENAI_API_KEY"]
        model["openai_base_url"] = DEFAULT_OPENAI_BASE_URL
        model["openai_api_style"] = "responses"
    elif provider == "openai-compatible":
        model["required_env"] = ["PROXY_API_KEY"]
        model["openai_api_style"] = "chat"
    elif provider == "anthropic":
        model["required_env"] = ["ANTHROPIC_API_KEY"]
    else:
        model["provider"] = "local"
        model["required_env"] = []
    config["model"] = model
    config["version"] = CONFIG_VERSION
    return config


def prompt_setup_config(config: dict[str, object], path: Path) -> dict[str, object]:
    runtime = child_dict(config, "runtime")
    panel = child_dict(config, "panel")
    model = child_dict(config, "model")
    paths = child_dict(config, "paths")
    startup = child_dict(config, "startup")

    print("Yizutt setup")
    print(f"Config: {path}")
    print("")

    runtime["host"] = prompt_text("Runtime host", runtime.get("host", "127.0.0.1"))
    runtime["port"] = prompt_int("Runtime port", runtime.get("port", 50200), 1, 65535)
    runtime["worker_base_port"] = prompt_int("Worker base port", runtime.get("worker_base_port", 50210), 1, 65535)
    panel["port"] = prompt_int("Workbench panel port", panel.get("port", 50280), 1, 65535)
    runtime["min_workers"] = prompt_int("Min workers", runtime.get("min_workers", 1), 0, 1024)
    runtime["max_workers"] = prompt_int("Max workers", runtime.get("max_workers", 2), int(runtime["min_workers"]), 1024)
    runtime["recovery_mode"] = prompt_choice("Startup recovery mode", ["none", "resume", "expire"], runtime.get("recovery_mode", "none"))
    startup["build"] = prompt_bool("Build Rust workspace before startup", bool(startup.get("build", True)))

    provider = prompt_choice("Model provider", ["local", "openai", "anthropic", "openai-compatible"], model.get("provider", "local"))
    model["provider"] = provider
    if provider == "local":
        mock_port = prompt_int("Local mock model port", runtime.get("mock_port", 50990), 1, 65535)
        runtime["mock_port"] = mock_port
        default_url = model.get("local_model_url") or f"http://127.0.0.1:{mock_port}"
        model["local_model_url"] = prompt_text("Local model URL", default_url)
        model["required_env"] = []
    elif provider == "openai":
        model["openai_model"] = prompt_text("OpenAI model", model.get("openai_model", DEFAULT_OPENAI_MODEL))
        model["openai_base_url"] = DEFAULT_OPENAI_BASE_URL
        model["openai_api_style"] = "responses"
        model["required_env"] = ["OPENAI_API_KEY"]
    elif provider == "anthropic":
        model["anthropic_model"] = prompt_text("Anthropic model", model.get("anthropic_model", DEFAULT_ANTHROPIC_MODEL))
        model["required_env"] = ["ANTHROPIC_API_KEY"]
    else:
        model["openai_base_url"] = prompt_text("OpenAI-compatible base URL", model.get("openai_base_url", "http://127.0.0.1:48327/v1"))
        model["openai_model"] = prompt_text("OpenAI-compatible model", model.get("openai_model", DEFAULT_OPENAI_MODEL))
        model["openai_api_style"] = "chat"
        model["required_env"] = ["PROXY_API_KEY"]

    if prompt_bool("Configure advanced paths", False):
        runtime["home"] = prompt_text("Runtime home", runtime.get("home", ".yizutt/runtime"))
        panel["history_path"] = prompt_text("Panel history DB", panel.get("history_path", ".yizutt/panel/history.sqlite3"))
        paths["log_dir"] = prompt_text("Log directory", paths.get("log_dir", ".yizutt/local-demo/logs"))
        paths["memory_path"] = prompt_text("Memory DB", paths.get("memory_path", ".yizutt/memory/work.sqlite3"))
        paths["skills_root"] = prompt_text("Skills root", paths.get("skills_root", ".yizutt/skills"))

    config["runtime"] = runtime
    config["panel"] = panel
    config["model"] = model
    config["paths"] = paths
    config["startup"] = startup
    return normalize_setup_config(config)


def prompt_text(label: str, default: object) -> str:
    default_text = str(default)
    value = input(f"{label} [{default_text}]: ").strip()
    return value or default_text


def prompt_int(label: str, default: object, min_value: int, max_value: int) -> int:
    while True:
        value = prompt_text(label, default)
        try:
            parsed = int(value)
        except ValueError:
            print(f"Enter a number from {min_value} to {max_value}.")
            continue
        if min_value <= parsed <= max_value:
            return parsed
        print(f"Enter a number from {min_value} to {max_value}.")


def prompt_choice(label: str, choices: list[str], default: object) -> str:
    default_text = str(default) if str(default) in choices else choices[0]
    while True:
        value = prompt_text(f"{label} ({'/'.join(choices)})", default_text)
        if value in choices:
            return value
        print(f"Choose one of: {', '.join(choices)}")


def prompt_bool(label: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        value = input(f"{label} [{suffix}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Enter y or n.")


def merge_dict(base: dict[str, object], overlay: dict[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dict(merged[key], value)  # type: ignore[arg-type]
        else:
            merged[key] = value
    return merged


def copy_option(env: dict[str, str], name: str, value: str | None) -> None:
    if value:
        env[name] = value


def exported_start_env(env: dict[str, str]) -> dict[str, str]:
    names = [
        "YIZUTT_PROJECT_ROOT",
        "YIZUTT_CONFIG_PATH",
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
        "YIZUTT_MODEL_PROVIDER",
        "YIZUTT_OPENAI_MODEL",
        "YIZUTT_OPENAI_BASE_URL",
        "YIZUTT_OPENAI_API_STYLE",
        "YIZUTT_ANTHROPIC_MODEL",
        "YIZUTT_LOCAL_MODEL_URL",
        "YIZUTT_MEMORY_PATH",
        "YIZUTT_SKILLS_ROOT",
    ]
    return {name: env[name] for name in names if name in env}


if __name__ == "__main__":
    raise SystemExit(main())
