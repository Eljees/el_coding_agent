from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

RichConsole: type | None
RichTable: type | None
try:  # pragma: no cover - exercised implicitly when rich is installed
    from rich.console import Console as RichConsole
    from rich.table import Table as RichTable
except Exception:
    RichConsole = None
    RichTable = None


class SimpleConsole:
    def print(self, *args: object, **kwargs: Any) -> None:
        # Drop rich-only keyword arguments (highlight, style, justify, markup,
        # overflow, ...) so call sites written for rich.Console.print do not
        # crash when the optional ``rich`` extra is absent and this stdlib
        # fallback is used instead.
        builtin_keys = {"sep", "end", "file", "flush"}
        safe = {key: value for key, value in kwargs.items() if key in builtin_keys}
        print(*args, **safe)

    def print_json(self, data: str | dict[str, Any]) -> None:
        if isinstance(data, str):
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                print(data)
                return
        else:
            payload = data
        print(json.dumps(payload, ensure_ascii=False, indent=2))


@dataclass
class SimpleTable:
    title: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)

    def add_column(self, name: str) -> None:
        self.columns.append(name)

    def add_row(self, *values: object) -> None:
        self.rows.append([str(value) for value in values])

    def __str__(self) -> str:
        widths = [len(column) for column in self.columns]
        for row in self.rows:
            for idx, cell in enumerate(row):
                if idx >= len(widths):
                    widths.append(len(cell))
                else:
                    widths[idx] = max(widths[idx], len(cell))
        lines: list[str] = []
        if self.title:
            lines.append(self.title)
        if self.columns:
            lines.append(
                " | ".join(self.columns[idx].ljust(widths[idx]) for idx in range(len(self.columns)))
            )
            lines.append("-+-".join("-" * width for width in widths))
        for row in self.rows:
            lines.append(" | ".join(row[idx].ljust(widths[idx]) for idx in range(len(row))))
        return "\n".join(lines)


def make_console(*, legacy_windows: bool | None = None) -> Any:
    if RichConsole is not None:
        if legacy_windows is None:
            return RichConsole()
        return RichConsole(legacy_windows=legacy_windows)
    return SimpleConsole()


def make_table(title: str | None = None) -> Any:
    if RichTable is not None:
        return RichTable(title=title)
    return SimpleTable(title=title)
