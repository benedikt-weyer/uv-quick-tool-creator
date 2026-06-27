# uv-quick-tool-creator

`uv-quick-tool-creator` creates new installable `uv` tool projects. It drives `uv init --package --app`, writes a `flake.nix` and `.envrc` into the generated project, and then opens the project in a configurable editor. The default editor is VS Code via `code -n`.

## Install

Install it as a uv-managed tool from this repository:

```bash
uv tool install /home/benedikt/Git/uv-quick-tool-creator
```

From the repository root, this is equivalent:

```bash
uv tool install .
```

On NixOS, prefer an explicit Nix-provided Python so `uv` does not select a downloaded generic Linux interpreter:

```bash
uv tool install --python "$(command -v python)" .
```

This repository also includes a shell installer that finds a Nix-store Python and uses it automatically:

```bash
sh ./install-nixos.sh
```

After `direnv allow`, the wrapper commands in `script-wrappers/` are also added to `PATH`:

```bash
install-nixos
```

To update or reinstall this tool on NixOS:

```bash
sh ./update-nixos.sh
```

With direnv active, you can also run:

```bash
update-nixos
```

To reinstall over an existing tool install with extra `uv tool install` flags:

```bash
sh ./update-nixos.sh --editable
```

If you want that behavior globally for tool installs, you can also use:

```bash
UV_NO_MANAGED_PYTHON=1 uv tool install .
```

This avoids the `Could not start dynamically linked executable` failure from a uv-managed Python under `~/.local/share/uv/python`.

## Configure

Write a default config file:

```bash
uv-quick-tool-creator init-config
```

That writes `~/.config/uv-quick-tool-creator/config.yaml`. An example config is included in [uv-quick-tool-creator.example.yaml](/home/benedikt/Git/uv-quick-tool-creator/uv-quick-tool-creator.example.yaml).

Example:

```yaml
tools_directory: ~/Git/tools
editor_command: code
editor_args:
	- -n
author_from: auto
build_backend: uv
python: null
vcs: git
```

`tools_directory` controls where new tool projects are created by default. `editor_command` and `editor_args` control how the new project is opened after setup.

## Usage

Create a new tool project in `tools_directory/<name>` and open it in VS Code:

```bash
uv-quick-tool-creator create my-new-tool --description "My new uv tool"
```

Create a project at an explicit path:

```bash
uv-quick-tool-creator create my-new-tool --path ~/work/my-new-tool
```

Create a project without opening an editor:

```bash
uv-quick-tool-creator create my-new-tool --no-open
```

Install a generated local tool project into `uv tool`:

```bash
uv-quick-tool-creator install my-new-tool
```

List generated tool projects in your configured tools directory:

```bash
uv-quick-tool-creator list
```

Show each project path as well:

```bash
uv-quick-tool-creator list --paths
```

Install it in editable mode:

```bash
uv-quick-tool-creator install my-new-tool --editable
```

Update an installed tool from the local project source:

```bash
uv-quick-tool-creator update my-new-tool
```

Open an existing tool project in the configured editor:

```bash
uv-quick-tool-creator edit my-new-tool
```

Uninstall a tool from `uv tool` without deleting its project directory:

```bash
uv-quick-tool-creator uninstall my-new-tool
```

The generated project is created with `uv init --package --app --no-workspace`, includes an installable script entry from `uv init`, and also gets:

```text
flake.nix
.envrc
```

The `.envrc` uses `use flake path:./`, which works cleanly with uncommitted local flakes.
