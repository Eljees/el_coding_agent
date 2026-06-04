# Troubleshooting

## The LLM endpoint is unreachable

`doctor` reports `llm endpoint: FAIL`. Confirm your vLLM server is up at the
configured `base_url` (default `http://localhost:8015/v1`) and the model name
matches. Use `--profile` to point at an alternative endpoint.

## git keeps failing with `.lock` files or a corrupt index

Symptoms: `Unable to create '.git/index.lock'`, `cannot lock ref 'HEAD'`,
`index file corrupt`.

**Root cause:** the repository lives inside a cloud-synced folder (e.g.
Yandex.Disk / Dropbox / OneDrive) and the sync client touches `.git`,
recreating lock files and corrupting the index.

Fix now:
```powershell
# pause the sync client first
del .git\index.lock ; del .git\HEAD.lock
del .git\index ; git reset      # rebuilds the index from HEAD (changes kept)
```

**Permanent fix:** move the repo out of the synced folder (e.g.
`D:\code\el_coding_agent`), or exclude `.git` from sync.

## `ruff` / `mypy` / `pytest` "not recognized" or launcher errors

`Fatal error in launcher ... cannot find ...python.exe` means the `.venv` was
created at a different path and the project folder was moved. Virtualenvs are
not relocatable — recreate it:

```powershell
deactivate
Remove-Item -Recurse -Force .venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Then prefer `python -m ruff` / `python -m mypy` / `python -m pytest`.

## `mypy` errors after editing

The gate is green on `mypy==1.14.1`. If you add code, keep it typed; widen LLM
client params to `SupportsChat` (not the concrete client). `rich` is an
optional import — `rich.*` is in the mypy ignore-missing-imports overrides.

## A capability plugin misbehaves

Plugins are isolated: a broken one is skipped with a warning. Use
`plugins list` to see what loaded and from where.
