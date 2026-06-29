from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


CommandHandler = Callable[[argparse.Namespace], int | None]
ParserConfigurer = Callable[[argparse.ArgumentParser], None]


class CliError(Exception):
    pass


@dataclass(frozen=True)
class RegisteredCommand:
    name: str
    help_text: str
    configure_parser: ParserConfigurer | None
    handler: CommandHandler


class CommandRegistryCli:
    def __init__(self, prog: str, description: str = ""):
        self.prog = prog
        self.description = description or f"CLI for {prog}."
        self._commands: dict[str, RegisteredCommand] = {}

    def command(
        self,
        name: str,
        *,
        help_text: str,
        configure_parser: ParserConfigurer | None = None,
    ) -> Callable[[CommandHandler], CommandHandler]:
        def decorator(handler: CommandHandler) -> CommandHandler:
            if name in self._commands:
                raise ValueError(f"Command already registered: {name}")

            self._commands[name] = RegisteredCommand(
                name=name,
                help_text=help_text,
                configure_parser=configure_parser,
                handler=handler,
            )
            return handler

        return decorator

    def build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog=self.prog,
            description=self.description,
        )
        parser.add_argument(
            "--version",
            action="version",
            version="%(prog)s 0.1.0",
        )

        subparsers = parser.add_subparsers(dest="command", required=True)
        for command in self._commands.values():
            command_parser = subparsers.add_parser(
                command.name,
                help=command.help_text,
                description=command.help_text,
            )
            if command.configure_parser is not None:
                command.configure_parser(command_parser)
            command_parser.set_defaults(_command_handler=command.handler)

        return parser

    def run(self, argv: list[str] | None = None) -> int:
        parser = self.build_parser()
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
        handler = getattr(args, "_command_handler", None)
        if handler is None:
            raise CliError("No command handler was selected.")

        result = handler(args)
        return 0 if result is None else result


def namespace_to_dict(args: argparse.Namespace) -> dict[str, Any]:
    return {
        key: value
        for key, value in vars(args).items()
        if not key.startswith("_")
    }