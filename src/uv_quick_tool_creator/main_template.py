from __future__ import annotations

import argparse
import json
import sys

from .cli import CliError, CommandRegistryCli


cli = CommandRegistryCli(
    prog=__SCRIPT_NAME__,
    description=__DESCRIPTION__,
)


def configure_health(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the health check response as JSON.",
    )


@cli.command("health", help_text="Run a minimal health check.", configure_parser=configure_health)
def run_health(args: argparse.Namespace) -> int:
    payload = {"status": "ok", "app": cli.prog}
    if args.json:
        print(json.dumps(payload))
    else:
        print(f"{cli.prog}: ok")
    return 0


def configure_echo(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("text", nargs="+", help="Text to print.")
    parser.add_argument(
        "--uppercase",
        action="store_true",
        help="Convert the output text to uppercase.",
    )


@cli.command("echo", help_text="Echo text to stdout.", configure_parser=configure_echo)
def run_echo(args: argparse.Namespace) -> int:
    message = " ".join(args.text)
    if args.uppercase:
        message = message.upper()
    print(message)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return cli.run(argv)
    except CliError as exc:
        print(exc, file=sys.stderr)
        return 1