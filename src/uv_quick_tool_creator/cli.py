from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_serializer, field_validator

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "uv-quick-tool-creator" / "config.yaml"

FLAKE_TEMPLATE = """{
  description = \"Development shell for {project_name}\";

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uv-quick-tool-creator",
        description="Create packaged uv tool projects with a configurable dev shell.",
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

    return parser


def load_config(path: Path) -> AppConfig:
    config_path = path.expanduser()
    if not config_path.exists():
        return AppConfig()

    raw_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if raw_data is None:
        raw_data = {}
    if not isinstance(raw_data, dict):
        raise SystemExit(f"Config file must contain a YAML mapping: {config_path}")

    try:
        return AppConfig.model_validate(raw_data)
    except ValidationError as exc:
        raise SystemExit(f"Invalid config file {config_path}:\n{exc}") from exc


def write_config(path: Path, config: AppConfig, force: bool) -> int:
    config_path = path.expanduser()
    if config_path.exists() and not force:
        raise SystemExit(f"Config file already exists: {config_path}. Use --force to overwrite it.")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    dumped = yaml.safe_dump(config.model_dump(mode="json", exclude_none=True), sort_keys=False)
    config_path.write_text(dumped, encoding="utf-8")
    print(f"Wrote config to {config_path}")
    return 0


def create_project(name: str, description: str, path: Path | None, config: AppConfig, open_in_editor: bool) -> int:
    project_dir = (path.expanduser() if path is not None else config.tools_directory / name)

    if project_dir.exists() and any(project_dir.iterdir()):
        raise SystemExit(f"Target directory already exists and is not empty: {project_dir}")

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

    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc

    write_flake(project_dir, name)
    write_envrc(project_dir)

    print(f"Created {name} at {project_dir}")

    if open_in_editor:
        open_project(project_dir, config)
        print(f"Opened {project_dir} with {config.editor_command}")

    return 0


def write_flake(project_dir: Path, project_name: str) -> None:
    flake_path = project_dir / "flake.nix"
    flake_path.write_text(FLAKE_TEMPLATE.format(project_name=project_name), encoding="utf-8")


def write_envrc(project_dir: Path) -> None:
    envrc_path = project_dir / ".envrc"
    envrc_path.write_text(ENVRC_CONTENT, encoding="utf-8")


def open_project(project_dir: Path, config: AppConfig) -> None:
    command = [config.editor_command, *config.editor_args, str(project_dir)]
    try:
        subprocess.Popen(command)
    except OSError as exc:
        raise SystemExit(
            f"Project was created at {project_dir}, but opening it with {config.editor_command!r} failed: {exc}"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init-config":
        target_path = args.path if args.path is not None else args.config
        return write_config(target_path, AppConfig(), args.force)

    if args.command == "create":
        config = load_config(args.config)
        return create_project(args.name, args.description, args.path, config, not args.no_open)

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())