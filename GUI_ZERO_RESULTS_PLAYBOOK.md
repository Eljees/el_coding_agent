# GUI Zero Results Playbook

Дата: 2026-05-13

## Когда применять

Применять этот регламент, если GUI scan через:

- `python -m local_codex_lite ui`
- `CommandCenterUI -> evidence.cve_scan -> cmd_evidence_cve_scan -> skills/cve-bin-tool/run_cve_scan.py`

даёт `0` findings по артефакту, для которого в истории уже были ненулевые результаты.

## Основное правило

Нулевой GUI-result нельзя считать доказательством отсутствия CVE, если:

- для того же артефакта уже есть historical non-zero;
- не подтверждена полнота unpack/inventory;
- не подтверждён tool/db state;
- scan мог завершиться частично или с деградировавшим evidence.

В таком случае `0` трактуется как сигнал на расследование и исправление.

## Порядок действий

1. Сохранить текущее evidence без интерпретации:
   - `status.json`
   - `cve_summary.json`
   - raw JSON output
   - `cve_report.md`
   - `high_critical_report_<date>.md`, если был сформирован
   - SHA артефакта
   - имя и путь артефакта
   - tool version
   - DB snapshot / update state

2. Сопоставить текущий нулевой GUI-run с historical non-zero:
   - тот же ли это артефакт;
   - совпадает ли SHA;
   - какой инструмент давал non-zero раньше;
   - тот же ли severity threshold;
   - тот же ли unpack path;
   - нет ли расхождения в DB/tool snapshot;
   - не изменился ли runner path.

3. Классифицировать вероятную причину:
   - `gui-routing-defect`
   - `unpack-or-inventory-defect`
   - `db-drift`
   - `severity-filter-defect`
   - `timeout-or-partial-run`
   - `summary-classification-defect`
   - `historical-reference-mismatch`

4. Составить минимальный план исправления:
   - исправлять сначала путь воспроизведения;
   - не смешивать evidence collection и remediation;
   - не делать широких рефакторингов до восстановления historical signal.

5. После исправления повторно запустить scan только на артефактах с historical non-zero.

6. Сравнить три состояния:
   - historical non-zero
   - текущий проблемный zero-result
   - post-fix rerun

7. Только после этого фиксировать вывод:
   - signal restored
   - signal still missing
   - result inconclusive

## Приоритет повторных прогонов

1. Артефакты с подтверждённым historical non-zero.
2. Артефакты, где container-run и GUI-run расходятся.
3. Остальные кейсы.

## Что проверять в первую очередь

1. GUI intent routing и правильность вызова `evidence.cve_scan`.
2. Полноту unpack и наличие реального inventory.
3. Логику severity threshold и фильтров отчёта.
4. Состояние `cve-bin-tool` и DB snapshot.
5. Timeout, partial-run и fallback behavior.
6. Корректность `status.json` и `cve_summary.json`.

## Критерий для планирования исправлений

Исправления обязательны, если одновременно выполняются оба условия:

- текущий GUI result равен `0`;
- historical result по тому же артефакту больше `0`.

## Критерий успешного восстановления

Исправление считается успешным, если после минимального изменения GUI-path снова воспроизводит ожидаемый ненулевой сигнал на historical-positive артефакте.
