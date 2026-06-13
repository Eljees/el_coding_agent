# Cross-platform developer tasks (Linux / macOS parity for the *.ps1 helpers).
# Targets mirror .github/workflows/ci.yml so `make check` == CI locally.
#
# Usage:
#   make setup           # create env deps (editable + [dev] extras)
#   make check           # full gate: lint + format-check + typecheck + test
#   make run TASK="fix the bug in x.py" [APPLY=1] [EXEC=1] [DRY=1]
#   make ask Q="how does patch repair work?"

PY ?= python
PKG := local_codex_lite

.PHONY: help setup lint format format-check typecheck test smoke check doctor run ask

help:
	@echo "targets: setup lint format format-check typecheck test smoke check doctor run ask"

setup:
	$(PY) -m pip install -e ".[dev]"

lint:
	ruff check $(PKG)/ tests/

format:
	ruff format $(PKG)/ tests/

format-check:
	ruff format --check $(PKG)/ tests/

typecheck:
	mypy $(PKG)/

test:
	pytest -q --tb=short --cov=$(PKG) --cov-report=term --cov-fail-under=88

smoke:
	$(PY) tools/stdlib_smoke.py

gen-cli-ref:
	$(PY) scripts/gen_cli_reference.py

cli-ref-check:
	$(PY) scripts/gen_cli_reference.py --check

# Full local gate, identical to the CI lint+test job.
check: lint format-check typecheck test smoke cli-ref-check

doctor:
	$(PY) -m $(PKG) doctor

# make run TASK="..." [DRY=1] [APPLY=1] [EXEC=1]
run:
	$(PY) -m $(PKG) run "$(TASK)" $(if $(DRY),--dry-run,) $(if $(APPLY),--apply,) $(if $(EXEC),--exec,)

# make ask Q="..."
ask:
	$(PY) -m $(PKG) ask "$(Q)"
