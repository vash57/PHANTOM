#!/usr/bin/env python3
"""PHANTOM.exe — the ghost living inside your terminal.

A local-first AI developer companion powered by Ollama.  Run ``phantom.py``
with no arguments for the interactive séance, or use ``--status`` to inspect
the machine without starting one.
"""

from __future__ import annotations

import argparse
import sys
import traceback

from config import load_config
from src import __challenge__, __license__, __project__, __tagline__, __version__
from src.app import PhantomApp
from src.memory import MemoryStoreError
from src.personality import find_personality, personality_slugs
from src.themes import THEMES, find_theme
from src.utils import configure_stdio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phantom",
        description=f"{__project__} — {__tagline__}",
        epilog=f"{__challenge__} · {__license__}",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{__project__} {__version__}",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="check Ollama, the model, memory and the local environment, then exit",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="list saved local sessions, then exit",
    )
    session_group = parser.add_mutually_exclusive_group()
    session_group.add_argument(
        "--resume",
        action="store_true",
        help="resume the most recently updated session",
    )
    session_group.add_argument(
        "--session",
        metavar="ID",
        help="load a saved session by id or unique prefix",
    )
    parser.add_argument(
        "--model",
        metavar="NAME",
        help="use a different Ollama model for this run",
    )
    parser.add_argument(
        "--personality",
        metavar="NAME",
        choices=personality_slugs(),
        help="choose the active presence: " + ", ".join(personality_slugs()),
    )
    parser.add_argument(
        "--theme",
        metavar="NAME",
        choices=list(THEMES),
        help="choose a colour palette: " + ", ".join(THEMES),
    )
    parser.add_argument(
        "--no-animation",
        action="store_true",
        help="disable boot animation, typewriter, glitches and whispers",
    )
    parser.add_argument(
        "--no-boot",
        action="store_true",
        help="skip the boot sequence (the logo and intro remain)",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="use the ANSI/plain renderer instead of Rich panels",
    )
    color_group = parser.add_mutually_exclusive_group()
    color_group.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI colour",
    )
    color_group.add_argument(
        "--color",
        action="store_true",
        help="force ANSI colour even when stdout is not a tty",
    )
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        default=".env",
        help="load configuration from PATH (default: .env)",
    )
    parser.add_argument(
        "--no-env",
        action="store_true",
        help="ignore .env and use process environment plus defaults",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="show full tracebacks for unexpected failures",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_stdio()

    env_file = None if args.no_env else args.env_file
    config = load_config(env_file=env_file)

    if args.model:
        model = args.model.strip()
        if not model:
            parser.error("--model cannot be empty")
        config.model = model
    if args.personality:
        personality = find_personality(args.personality)
        if personality is None:
            parser.error(f"unknown personality: {args.personality}")
        config.personality = personality.slug
    if args.theme and find_theme(args.theme) is None:
        parser.error(f"unknown theme: {args.theme}")
    if args.no_animation:
        config.animation = False

    color: bool | None = None
    if args.no_color:
        color = False
    elif args.color:
        color = True

    try:
        app = PhantomApp(
            config,
            theme=args.theme or "phosphor",
            plain=args.plain,
            color=color,
            debug=args.debug,
        )
        if args.status:
            return app.status()
        if args.list_sessions:
            return app.list_sessions()
        return app.run(
            resume=args.resume,
            session_id=args.session,
            show_boot=not args.no_boot,
        )
    except KeyboardInterrupt:
        print("\nThe signal fades. Nothing was left running.", file=sys.stderr)
        return 130
    except MemoryStoreError as exc:
        print(f"PHANTOM could not open local memory: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        if getattr(args, "debug", False):
            traceback.print_exc()
        else:
            print(f"PHANTOM could not start: {exc}", file=sys.stderr)
            print("Run with --debug for a traceback.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
