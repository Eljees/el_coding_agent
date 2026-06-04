# Contributing to local-codex-lite

Thanks for taking the time to look at this project.  `local-codex-lite` is a
minimal local coding-agent MVP for Windows / PowerShell; the goal is to keep
it small, readable and safe by default.  See [`AGENTS.md`](AGENTS.md) for the
non-negotiable rules and the full architecture notes.

## Quick dev setup

```powershell
cd D:\!ya_drive_sync\YandexDisk\rostel\code\el_coding_agent
.\scripts\setup.ps1                       # creates .venv and installs [dev]
# Optional: route pip through a local proxy
copy tools\proxy.local.ps1.example tools\proxy.local.ps1
.\scripts\setup.ps1 -WithPipIni
```

Once the venv is active, the standard loop is:

```powershell
ruff check local_codex_lite/ tests/
ruff format --check local_codex_lite/ tests/
mypy local_codex_lite/
pytest -q
```

The same checks run automatically on every commit if `pre-commit` is wired
in:

```powershell
pre-commit install
pre-commit run --all-files   # one-off full sweep
```

## Branching & commits

- Work on a feature branch off `test/artifact-unpack`.  `main` is the
  long-lived integration branch.
- One coherent change per commit.  The commit message should say *why*, not
  just *what*.  See recent `stage 1` / `stage 2` / `stage 3a` / `stage 3b`
  / `stage 4` commits for the expected shape (single-line subject, blank
  line, then a bulleted body).
- Touch as few files as the change needs.  `cli.py` and `runner.py` are
  particularly easy to break, so prefer adding a helper module over piling
  more logic into either of them.

## Safety constraints (don't break these)

`AGENTS.md` has the full list.  The short version that the test suite
enforces:

- `--apply` is required to write files; `--exec` is required to run
  suggested commands.
- Sensitive paths (`.env`, `*secret*`, `*token*`, `*credential*`, ...)
  stay unreadable unless `allow_sensitive_read=true`.
- The dangerous-command blocklist in `safety.py` must keep rejecting at
  least the patterns covered by `tests/test_safety.py`.
- Patches outside the workspace, comment-only patches and empty patches
  are rejected before reaching `git apply`.

## Adding a capability

1. Define it in `local_codex_lite/capabilities.py` with required inputs and
   safety level.
2. Teach `intent._missing_inputs` how to validate the new `required_inputs`
   names if they don't fit existing slots
   (`_PATH_INPUTS` / `_JSON_PATH_INPUTS` / `_REPO_URL_OR_FILE_INPUTS`).
3. Add a regression test in `tests/test_intent.py`.
4. Wire the dispatch in `cli.py` -> the appropriate command handler.

## Tests

- Hit `pytest -q` locally before opening a PR.  CI runs the same suite
  with coverage on Ubuntu (3.11, 3.12) and Windows (3.12).
- For a quick sanity check without spinning up the full dev stack,
  ``python tools/stdlib_smoke.py`` runs the stdlib-only core (~60
  tests, sub-second) with no third-party imports required.  CI runs it
  as a fast pre-job before the main matrix.
- New behaviour needs a test; bug fixes need a regression test that fails
  on the un-patched code.
- Avoid hitting the real LLM endpoint in tests.  Stub
  `OpenAICompatibleClient` (the smoke harness under
  `tests/test_planner_retry.py` is a good template).
- Tests must not depend on `.local-codex-lite/runs/` from previous runs.

## Mutation testing (optional)

The four safety-critical modules -- ``safety.py``, ``patcher.py``,
``patch_errors.py``, ``llm_client.py`` -- are wired into ``mutmut`` so any
gap in the test suite shows up as a surviving mutation.  Run it locally
on demand:

```powershell
pip install -e ".[dev]"
mutmut run
mutmut results
mutmut html        # writes html/index.html with a clickable survivor list
mutmut show <id>   # inspect a specific mutant by id
```

CI runs ``mutmut`` weekly via ``.github/workflows/mutmut.yml``; PRs are
deliberately **not** gated on the mutation score.  Treat survivors as
follow-up issues to file, not blockers.  When you add or harden tests
that kill survivors, mention the dropped count in the commit message.

## Capability plugins (entry-points)

Third-party packages can extend the agent's capability list without
forking the repo.  See ``examples/sample_capability_plugin/`` for a
ready-to-install reference plugin -- copy the layout, rename the
package, swap the ``Capability`` definitions, and ``pip install -e .``
in the same venv where ``local-codex-lite`` lives.  Built-in
capabilities always win on id collisions, so namespace your ids
(``my_team.foo``) to stay out of the safety-critical core.

## Reporting issues

Open an issue with:

- the command you ran (full argv),
- the run-dir under `.local-codex-lite/runs/<timestamp>/` (zip if it's
  large),
- the relevant `events.jsonl` lines,
- and `python -m local_codex_lite doctor` output.

Please do **not** paste tokens, GitLab credentials or scan findings into
public issues.  See [`SECURITY.md`](SECURITY.md) for how to report a
security-relevant bug.
