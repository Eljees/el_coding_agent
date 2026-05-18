# sample-capability-plugin

A minimal reference implementation of a `local-codex-lite` capability
plugin, distributed as its own installable package.

## What this demonstrates

`local_codex_lite.capabilities.discover_capabilities()` walks the
`local_codex_lite.capabilities` entry-point group on every CLI / GUI
startup and merges anything it finds into the built-in list.  This
package shows the smallest possible plugin that produces a usable
`Capability`:

- `pyproject.toml` registers `sample_capabilities` under the
  `[project.entry-points."local_codex_lite.capabilities"]` group.
- `sample_capability_plugin/capabilities.py::provide` returns a single
  `Capability` named `sample.echo` with `safety_level="safe"` and no
  side effects.

## Install in editable mode

From this directory, in the same Python environment where
`local-codex-lite` is installed:

```powershell
pip install -e .
```

(Editable install is the easiest way to iterate -- you can edit
`capabilities.py` and re-run `python -m local_codex_lite recognize`
without reinstalling.)

## Verify the plugin is picked up

```powershell
python -m local_codex_lite plugins list --plugins-only
```

A row tagged `plugin / sample_capabilities / sample.echo` should
appear.  If nothing is printed under `--plugins-only`, the plugin
hasn't been installed into the active venv.

To confirm the routing layer also sees it:

```powershell
python -m local_codex_lite recognize "echo hello world"
```

The JSON output should show `"intent": "sample.echo"` once the plugin
is installed.  Without the plugin, the same task falls through to the
`run.preview` / `run.apply` family or to the unknown-task fallback.

## Safety guarantees you can rely on

- Built-in capabilities **always win on id collisions**.  A plugin that
  registers `run.apply` (or any other reserved id) is silently dropped.
- A misbehaving provider -- one that raises, returns an int instead of
  a `Capability`, or hides garbage inside a returned list -- is logged
  as a warning by `local_codex_lite.capabilities` and skipped.  Other
  plugins, and the built-in capabilities, are unaffected.
- The provider is called every time `discover_capabilities()` runs, so
  it should be cheap and free of side effects.

## Removing the plugin

```powershell
pip uninstall lcl-sample-capability-plugin
```
