from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from typing import Sequence


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentfabric", description="AgentFabric CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    ui = sub.add_parser("ui", help="Launch the AgentFabric web UI (Streamlit)")
    ui.add_argument("--config", dest="config_path", required=False, help="Path to YAML config")
    ui.add_argument("--host", default="127.0.0.1", help="Streamlit host")
    ui.add_argument("--port", type=int, default=8501, help="Streamlit port")
    ui.add_argument(
        "--toolbar-mode",
        default="developer",
        choices=["auto", "developer", "viewer", "minimal"],
        help=(
            "Streamlit toolbar mode (top-right controls). "
            "Use 'viewer' to keep the menu but hide developer options; "
            "use 'minimal' to hide most/all toolbar items; 'developer' to show."
        ),
    )
    ui.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open a browser window automatically",
    )

    return p


def _cmd_ui(args: argparse.Namespace) -> int:
    env = os.environ.copy()
    if args.config_path:
        env["AGENTFABRIC_UI_CONFIG_PATH"] = str(args.config_path)

    # Streamlit supports config via CLI flags and env vars; set both for robustness.
    # Env var name follows Streamlit's convention: STREAMLIT_<SECTION>_<OPTION>.
    if getattr(args, "toolbar_mode", None):
        env["STREAMLIT_CLIENT_TOOLBARMODE"] = str(args.toolbar_mode)

    try:
        import streamlit  # noqa: F401
    except Exception:
        print(
            "streamlit import failed. If you installed from source, re-sync deps:\n"
            "  uv sync\n"
            "Or reinstall the package with its dependencies.",
            file=sys.stderr,
        )
        return 2

    spec = importlib.util.find_spec("agentfabric.ui.app")
    app_path = getattr(spec, "origin", None)
    if not app_path:
        print("Could not locate agentfabric.ui.app module file.", file=sys.stderr)
        return 2

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        app_path,
        "--client.toolbarMode",
        str(args.toolbar_mode),
        "--server.address",
        str(args.host),
        "--server.port",
        str(int(args.port)),
    ]
    if args.no_browser:
        cmd.append("--server.headless=true")

    # Streamlit handles printing a local URL; keep output attached.
    raise SystemExit(subprocess.call(cmd, env=env))


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.cmd == "ui":
        return _cmd_ui(args)

    parser.error(f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
