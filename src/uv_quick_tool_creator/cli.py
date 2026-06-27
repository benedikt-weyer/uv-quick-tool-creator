from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_serializer, field_validator

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "uv-quick-tool-creator" / "config.yaml"

FLAKE_TEMPLATE = """{
    description = \"Development shell for __PROJECT_NAME__\";

  inputs = {
    nixpkgs.url = \"github:NixOS/nixpkgs/nixos-unstable\";
  };

  outputs = {{ nixpkgs, ... }}:
    let
      systems = [
        \"x86_64-linux\"
        \"aarch64-linux\"
        \"x86_64-darwin\"
        \"aarch64-darwin\"
      ];
      forAllSystems = f:
        nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${{system}});
    in
    {{
      devShells = forAllSystems (pkgs: {{
        default = pkgs.mkShell {{
          packages = with pkgs; [
            python3
            uv
          ];

          UV_PYTHON_DOWNLOADS = \"never\";
        }};
      }});
    }};
}}
"""

ENVRC_CONTENT = "use flake path:./\n"
INTERACTIVE_META_COMMANDS = ("help", "exit", "quit")
COMMAND_OPTIONS: dict[str, tuple[str, ...]] = {
    "init-config": ("--path", "--force"),
    "create": ("--description", "--path", "--no-open"),
    "install": ("--path", "--editable", "--force"),
    "update": ("--path", "--editable"),
    "edit": ("--path",),
    "list": ("--paths",),
}


class CliError(Exception):
    pass


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools_directory: Path = Field(default=Path.home() / "Git" / "tools")
    editor_command: str = Field(default="code", min_length=1)
    editor_args: list[str] = Field(default_factory=lambda: ["-n"])
    author_from: Literal["auto", "git", "none"] = "auto"
    build_backend: Literal[
        "uv", "hatch", "flit", "pdm", "poetry", "setuptools", "maturin", "scikit"
    ] = "uv"
    python: str | None = None
    vcs: Literal["git", "none"] = "git"

    @field_validator("tools_directory", mode="before")
    @classmethod
    def expand_tools_directory(cls, value: Any) -> Path:
        if isinstance(value, Path):
            return value.expanduser()
        if isinstance(value, str):
            return Path(value).expanduser()
        raise TypeError("tools_directory must be a path or string")

    @field_validator("editor_command")
    @classmethod
    def normalize_editor_command(cls, value: str) -> str:
        command = value.strip()
        if not command:
            raise ValueError("editor_command cannot be empty")
        return command

    @field_serializer("tools_directory")
    def serialize_tools_directory(self, value: Path) -> str:
        return str(value)


class InteractiveCompleter(Completer):
    def __init__(self, config_path: Path):
        self.config_path = config_path.expanduser()

    def get_completions(self, document: Any, complete_event: Any) -> Any:
        del complete_event
        text = document.text_before_cursor
        stripped = text.lstrip()
        ends_with_space = text.endswith(" ")
        parts = stripped.split()

        if not parts:
            yield from self._complete_commands("")
            return

        if len(parts) == 1 and not ends_with_space:
            yield from self._complete_commands(parts[0])
            return

        command = parts[0]
        if command in INTERACTIVE_META_COMMANDS:
            return

        current = "" if ends_with_space else parts[-1]
        completed_args = parts[1:] if ends_with_space else parts[1:-1]

        if command in {"install", "update", "edit", "uninstall"} and len(completed_args) == 0 and not current.startswith("--"):
            yield from self._complete_tool_names(current)
            return

        for option in COMMAND_OPTIONS.get(command, ()): 
            if option.startswith(current):
                yield Completion(option, start_position=-len(current))

    def _complete_commands(self, prefix: str) -> Any:
        for command in [*COMMAND_OPTIONS.keys(), "uninstall", "interactive", *INTERACTIVE_META_COMMANDS]:
            if command.startswith(prefix):
                yield Completion(command, start_position=-len(prefix))

    def _complete_tool_names(self, prefix: str) -> Any:
        for tool_name in get_local_tool_names(load_config(self.config_path)):
            if tool_name.startswith(prefix):
                yield Completion(tool_name, start_position=-len(prefix))


def build_parser(exit_on_error: bool = True) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uv-quick-tool-creator",
        description="Create packaged uv tool projects with a configurable dev shell.",
        exit_on_error=exit_on_error,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"YAML config file to use (default: {DEFAULT_CONFIG_PATH})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_config = subparsers.add_parser("init-config", help="Write a default YAML config file.")
    init_config.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Write the config to a custom path instead of the default location.",
    )
    init_config.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing config file.",
    )

    create = subparsers.add_parser("create", help="Create a new uv tool project.")
    create.add_argument("name", help="Package and script name for the new tool project.")
    create.add_argument(
        "--description",
        default="",
        help="Project description to pass to uv init.",
    )
    create.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Target directory for the new project. Defaults to tools_directory/name.",
    )
    create.add_argument(
        "--no-open",
        action="store_true",
        help="Create the project without opening it in the configured editor.",
    )

    install = subparsers.add_parser("install", help="Install a generated tool project with uv.")
    install.add_argument("name", help="Tool name to install.")
    install.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Project directory to install from. Defaults to tools_directory/name.",
    )
    install.add_argument(
        "--editable",
        action="store_true",
        help="Install the tool in editable mode.",
    )
    install.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing tool installation.",
    )

    update = subparsers.add_parser("update", help="Reinstall a generated tool project from its local source.")
    update.add_argument("name", help="Tool name to update.")
    update.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Project directory to update from. Defaults to tools_directory/name.",
    )
    update.add_argument(
        "--editable",
        action="store_true",
        help="Reinstall the tool in editable mode.",
    )

    edit = subparsers.add_parser("edit", help="Open an existing tool project in the configured editor.")
    edit.add_argument("name", help="Tool name to open.")
    edit.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Project directory to open. Defaults to tools_directory/name.",
    )

    uninstall = subparsers.add_parser("uninstall", help="Uninstall a tool from uv.")
    uninstall.add_argument("name", help="Tool name to uninstall.")

    list_tools = subparsers.add_parser("list", help="List generated tool projects in the configured tools directory.")
    list_tools.add_argument(
        "--paths",
        action="store_true",
        help="Show the project path for each tool.",
    )

    subparsers.add_parser("interactive", help="Start an interactive shell with command autocompletion.")

    return parser


def load_config(path: Path) -> AppConfig:
    config_path = path.expanduser()
    if not config_path.exists():
        return AppConfig()

    raw_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if raw_data is None:
        raw_data = {}
    if not isinstance(raw_data, dict):
        raise CliError(f"Config file must contain a YAML mapping: {config_path}")

    try:
        return AppConfig.model_validate(raw_data)
    except ValidationError as exc:
        raise CliError(f"Invalid config file {config_path}:\n{exc}") from exc


def write_config(path: Path, config: AppConfig, force: bool) -> int:
    config_path = path.expanduser()
    if config_path.exists() and not force:
        raise CliError(f"Config file already exists: {config_path}. Use --force to overwrite it.")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    dumped = yaml.safe_dump(config.model_dump(mode="json", exclude_none=False), sort_keys=False)
    config_path.write_text(dumped, encoding="utf-8")
    print(f"Wrote config to {config_path}")
    return 0


def resolve_project_dir(name: str, path: Path | None, config: AppConfig) -> Path:
    if path is not None:
        return path.expanduser()
    return config.tools_directory / name


def ensure_project_dir(project_dir: Path) -> None:
    if not project_dir.exists():
        raise CliError(f"Project directory does not exist: {project_dir}")
    if not project_dir.is_dir():
        raise CliError(f"Project path is not a directory: {project_dir}")
    if not (project_dir / "pyproject.toml").exists():
        raise CliError(f"Project directory does not contain pyproject.toml: {project_dir}")


def run_command(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise CliError(f"Command failed with exit code {exc.returncode}: {' '.join(command)}") from exc


def get_local_tool_names(config: AppConfig) -> list[str]:
    tools_root = config.tools_directory
    if not tools_root.exists():
        return []

    return sorted(
        path.name for path in tools_root.iterdir() if path.is_dir() and (path / "pyproject.toml").exists()
    )


def get_installed_tool_names() -> set[str]:
    result = subprocess.run(["uv", "tool", "list"], check=False, capture_output=True, text=True)
    installed_tools: set[str] = set()
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.startswith("warning:"):
            continue
        installed_tools.add(stripped.split()[0])
    return installed_tools


def list_tools(config: AppConfig, show_paths: bool) -> None:
    tools_root = config.tools_directory
    if not tools_root.exists():
        print(f"No tools found in {tools_root}")
        return

    installed_tools = get_installed_tool_names()
    tool_dirs = [tools_root / tool_name for tool_name in get_local_tool_names(config)]

    if not tool_dirs:
        print(f"No tools found in {tools_root}")
        return

    for project_dir in tool_dirs:
        line = project_dir.name
        if project_dir.name in installed_tools:
            line += " (installed)"
        if show_paths:
            line += f"\t{project_dir}"
        print(line)


def create_interactive_session(config_path: Path, session: Any | None) -> Any:
    if session is not None:
        return session

    return PromptSession(
        completer=InteractiveCompleter(config_path),
        complete_while_typing=True,
        history=InMemoryHistory(),
    )


def print_interactive_help() -> None:
    print("Commands: create, install, update, edit, uninstall, list, init-config, help, exit, quit")


def run_interactive_command(command_line: str, config_path: Path, parser: argparse.ArgumentParser) -> None:
    try:
        command_argv = shlex.split(command_line)
    except ValueError as exc:
        print(f"Invalid command: {exc}")
        return

    if command_argv[0] == "interactive":
        print("Already in interactive mode.")
        return
    if any(token in {"-h", "--help"} for token in command_argv):
        print("Use `help` in interactive mode.")
        return

    try:
        args = parser.parse_args(["--config", str(config_path), *command_argv])
    except argparse.ArgumentError as exc:
        print(f"Invalid command: {exc}")
        return

    try:
        dispatch_command(args)
    except CliError as exc:
        print(exc)


def run_interactive(config_path: Path, session: Any | None = None) -> None:
    interactive_session = create_interactive_session(config_path, session)
    parser = build_parser(exit_on_error=False)

    print("Interactive mode. Press Tab for completions, type help for commands, and exit or Ctrl-D to quit.")
    while True:
        try:
            raw_command = interactive_session.prompt("uv-quick-tool-creator> ")
        except EOFError:
            print()
            return
        except KeyboardInterrupt:
            print()
            continue

        command_line = raw_command.strip()
        if not command_line:
            continue
        if command_line in {"exit", "quit"}:
            return
        if command_line == "help":
            print_interactive_help()
            continue

        run_interactive_command(command_line, config_path, parser)


def create_project(name: str, description: str, path: Path | None, config: AppConfig, open_in_editor: bool) -> int:
    project_dir = resolve_project_dir(name, path, config)

    if project_dir.exists() and any(project_dir.iterdir()):
        raise CliError(f"Target directory already exists and is not empty: {project_dir}")

    project_dir.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "uv",
        "init",
        "--package",
        "--app",
        "--no-workspace",
        "--vcs",
        config.vcs,
        "--author-from",
        config.author_from,
        "--build-backend",
        config.build_backend,
        "--name",
        name,
    ]
    if description:
        command.extend(["--description", description])
    if config.python:
        command.extend(["--python", config.python])
    command.append(str(project_dir))

    run_command(command)

    write_flake(project_dir, name)
    write_envrc(project_dir)

    print(f"Created {name} at {project_dir}")

    if open_in_editor:
        open_project(project_dir, config)
        print(f"Opened {project_dir} with {config.editor_command}")

    return 0


def install_tool(name: str, path: Path | None, config: AppConfig, editable: bool, force: bool, reinstall: bool) -> int:
    project_dir = resolve_project_dir(name, path, config)
    ensure_project_dir(project_dir)

    command = ["uv", "tool", "install", "--python", sys.executable]
    if editable:
        command.append("--editable")
    if force:
        command.append("--force")
    if reinstall:
        command.append("--reinstall")
    command.append(str(project_dir))

    run_command(command)

    action = "Updated" if reinstall else "Installed"
    print(f"{action} {name} from {project_dir}")
    return 0


def edit_tool(name: str, path: Path | None, config: AppConfig) -> int:
    project_dir = resolve_project_dir(name, path, config)
    ensure_project_dir(project_dir)
    open_project(project_dir, config)
    print(f"Opened {project_dir} with {config.editor_command}")
    return 0


def uninstall_tool(name: str) -> int:
    run_command(["uv", "tool", "uninstall", name])
    print(f"Uninstalled {name}")
    return 0


def write_flake(project_dir: Path, project_name: str) -> None:
    flake_path = project_dir / "flake.nix"
    flake_path.write_text(FLAKE_TEMPLATE.replace("__PROJECT_NAME__", project_name), encoding="utf-8")


def write_envrc(project_dir: Path) -> None:
    envrc_path = project_dir / ".envrc"
    envrc_path.write_text(ENVRC_CONTENT, encoding="utf-8")


def open_project(project_dir: Path, config: AppConfig) -> None:
    command = [config.editor_command, *config.editor_args, str(project_dir)]
    try:
        subprocess.Popen(command)
    except OSError as exc:
        raise CliError(
            f"Project was created at {project_dir}, but opening it with {config.editor_command!r} failed: {exc}"
        ) from exc


def dispatch_command(args: argparse.Namespace) -> int:
    if args.command == "init-config":
        target_path = args.path if args.path is not None else args.config
        return write_config(target_path, AppConfig(), args.force)

    if args.command == "create":
        config = load_config(args.config)
        return create_project(args.name, args.description, args.path, config, not args.no_open)

    if args.command == "install":
        config = load_config(args.config)
        return install_tool(args.name, args.path, config, args.editable, args.force, False)

    if args.command == "update":
        config = load_config(args.config)
        return install_tool(args.name, args.path, config, args.editable, False, True)

    if args.command == "edit":
        config = load_config(args.config)
        return edit_tool(args.name, args.path, config)

    if args.command == "uninstall":
        return uninstall_tool(args.name)

    if args.command == "list":
        config = load_config(args.config)
        list_tools(config, args.paths)
        return 0

    if args.command == "interactive":
        run_interactive(args.config)
        return 0

    raise CliError(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    effective_argv = sys.argv[1:] if argv is None else argv
    if not effective_argv:
        run_interactive(DEFAULT_CONFIG_PATH)
        return 0

    parser = build_parser()
    args = parser.parse_args(effective_argv)
    try:
        return dispatch_command(args)
    except CliError as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())