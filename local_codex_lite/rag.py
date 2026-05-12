from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import AgentConfig
from .safety import is_inside_workspace, is_sensitive_path

_BLOCKED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    ".local-codex-lite",
    ".vscode",
    "__old",
    "generated_projects",
}


@dataclass(frozen=True)
class Chunk:
    path: Path
    start_line: int
    end_line: int
    text: str
    sha256: str
    mtime: float


@dataclass(frozen=True)
class RetrievedChunk:
    path: Path
    start_line: int
    end_line: int
    text: str
    score: float
    reason: str = "keyword match"


@dataclass(frozen=True)
class RagIndexInfo:
    provider: str
    store_dir: Path
    index_path: Path
    metadata_path: Path
    status_path: Path
    chunk_count: int
    file_count: int


class RagProviderError(RuntimeError):
    pass


def rag_provider(cfg: AgentConfig) -> str:
    provider = (cfg.rag.provider or "keyword").strip().lower()
    return provider or "keyword"


def ensure_rag_provider_supported(cfg: AgentConfig) -> str:
    provider = rag_provider(cfg)
    if provider == "keyword":
        return provider
    if provider == "chroma":
        raise RagProviderError(
            "RAG provider 'chroma' is configured but not implemented in this build. "
            "Use provider: keyword."
        )
    raise RagProviderError(
        f"RAG provider '{provider}' is not recognized. Use provider: keyword."
    )


def resolve_store_dir(root: Path, cfg: AgentConfig) -> Path:
    store_dir = Path(cfg.rag.store_dir)
    if not store_dir.is_absolute():
        store_dir = root / store_dir
    store_dir = store_dir.resolve()
    if not is_inside_workspace(store_dir, root):
        raise RagProviderError("RAG store_dir must stay inside the workspace.")
    return store_dir


def build_chunks(root: Path, cfg: AgentConfig) -> list[Chunk]:
    ensure_rag_provider_supported(cfg)
    root = root.resolve()
    store_dir = resolve_store_dir(root, cfg)
    chunks: list[Chunk] = []
    blocked_rel = store_dir.relative_to(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dir_path = Path(dirpath)
        dirnames[:] = [name for name in dirnames if name not in _BLOCKED_DIRS]
        for filename in sorted(filenames):
            path = dir_path / filename
            rel_path = path.relative_to(root)
            if _is_blocked_rel_path(rel_path, blocked_rel):
                continue
            if any(part in _BLOCKED_DIRS for part in rel_path.parts[:-1]):
                continue
            if not _matches_any(rel_path, cfg.rag.include_globs):
                continue
            if _matches_any(rel_path, cfg.rag.exclude_globs):
                continue
            if not is_inside_workspace(path, root):
                continue
            if is_sensitive_path(path):
                continue
            if path.stat().st_size > cfg.workspace.max_file_bytes:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for start, end, chunk_text in _split_into_chunks(text, cfg.rag.chunk_chars, cfg.rag.overlap_chars):
                start_line, end_line = _offsets_to_line_numbers(text, start, end)
                chunks.append(
                    Chunk(
                        path=path,
                        start_line=start_line,
                        end_line=end_line,
                        text=chunk_text,
                        sha256=_hash_text(chunk_text),
                        mtime=path.stat().st_mtime,
                    )
                )
    return chunks


def index_workspace(root: Path, cfg: AgentConfig) -> RagIndexInfo:
    ensure_rag_provider_supported(cfg)
    root = root.resolve()
    store_dir = resolve_store_dir(root, cfg)
    store_dir.mkdir(parents=True, exist_ok=True)
    chunks = build_chunks(root, cfg)
    index_path = store_dir / "index.json"
    metadata_path = store_dir / "metadata.json"
    status_path = store_dir / "status.json"
    serialisable = [
        {
            "path": str(c.path.relative_to(root)),
            "start_line": c.start_line,
            "end_line": c.end_line,
            "text": c.text,
            "sha256": c.sha256,
            "mtime": c.mtime,
        }
        for c in chunks
    ]
    index_path.write_text(json.dumps(serialisable, ensure_ascii=False, indent=2), encoding="utf-8")
    metadata = {
        "kind": "rag_index",
        "provider": rag_provider(cfg),
        "created_at": _utc_now_iso(),
        "workspace_root": str(root),
        "store_dir": str(store_dir),
        "index_path": str(index_path),
        "file_count": len({chunk.path for chunk in chunks}),
        "chunk_count": len(chunks),
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    status = {
        "status": "ok",
        "message": "keyword RAG index built",
        "provider": rag_provider(cfg),
        "chunk_count": len(chunks),
        "file_count": len({chunk.path for chunk in chunks}),
    }
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return RagIndexInfo(
        provider=rag_provider(cfg),
        store_dir=store_dir,
        index_path=index_path,
        metadata_path=metadata_path,
        status_path=status_path,
        chunk_count=len(chunks),
        file_count=len({chunk.path for chunk in chunks}),
    )


def query_index(query: str, root: Path, cfg: AgentConfig, top_k: int | None = None) -> list[RetrievedChunk]:
    ensure_rag_provider_supported(cfg)
    root = root.resolve()
    store_dir = resolve_store_dir(root, cfg)
    if not (store_dir / "index.json").exists():
        index_workspace(root, cfg)
    chunks = _load_index(root, cfg)
    tokens = _tokenize_query(query)
    if not tokens:
        return []
    results: list[RetrievedChunk] = []
    for chunk in chunks:
        text_lower = chunk.text.lower()
        path_lower = chunk.path.as_posix().lower()
        matched = [token for token in tokens if token in text_lower or token in path_lower]
        if not matched:
            continue
        score = 0.0
        for token in matched:
            score += text_lower.count(token)
            if token in path_lower:
                score += 0.5
        results.append(
            RetrievedChunk(
                path=chunk.path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                text=chunk.text,
                score=score,
                reason=f"matched: {', '.join(dict.fromkeys(matched))}",
            )
        )
    results.sort(key=lambda item: (-item.score, item.path.as_posix().lower(), item.start_line))
    return results[: (top_k or cfg.rag.top_k)]


def retrieve_rag_context(
    query: str,
    root: Path,
    cfg: AgentConfig,
    *,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    return query_index(query, root, cfg, top_k=top_k)


def format_retrieved_context(chunks: list[RetrievedChunk], max_context_chars: int) -> str:
    parts: list[str] = []
    used = 0
    for chunk in chunks:
        snippet = _compact_snippet(chunk.text, max_context_chars=max_context_chars)
        if not snippet:
            continue
        header = f"### {chunk.path.as_posix()} [{chunk.start_line}-{chunk.end_line}] (score={chunk.score:.1f}; {chunk.reason})"
        block = f"{header}\n{snippet}"
        block_len = len(block)
        if parts and used + block_len > max_context_chars:
            break
        parts.append(block)
        used += block_len
    return "\n\n".join(parts).strip()


def _compact_snippet(text: str, max_context_chars: int) -> str:
    limit = max(80, min(800, max_context_chars // 3))
    snippet = text.strip()
    if len(snippet) > limit:
        snippet = snippet[: limit - 3].rstrip() + "..."
    return snippet


def _load_index(root: Path, cfg: AgentConfig) -> list[Chunk]:
    index_path = resolve_store_dir(root, cfg) / "index.json"
    if not index_path.exists():
        return []
    data = json.loads(index_path.read_text(encoding="utf-8"))
    chunks: list[Chunk] = []
    for item in data:
        chunks.append(
            Chunk(
                path=root / item["path"],
                start_line=item["start_line"],
                end_line=item["end_line"],
                text=item["text"],
                sha256=item["sha256"],
                mtime=item["mtime"],
            )
        )
    return chunks


def _split_into_chunks(text: str, chunk_chars: int, overlap: int) -> list[tuple[int, int, str]]:
    if len(text) <= chunk_chars:
        return [(0, len(text), text)]
    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        chunks.append((start, end, text[start:end]))
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks


def _offsets_to_line_numbers(text: str, start: int, end: int) -> tuple[int, int]:
    before = text[:start]
    start_line = before.count("\n") + 1 if before else 1
    up_to_end = text[:end].rstrip("\n")
    end_line = up_to_end.count("\n") + 1 if up_to_end else start_line
    return start_line, end_line


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tokenize_query(query: str) -> list[str]:
    tokens = [token for token in re.split(r"\W+", query.lower()) if len(token) >= 2]
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


def _matches_any(path: Path, patterns: list[str]) -> bool:
    return any(path.match(pattern) or _match_glob_prefix(path, pattern) for pattern in patterns)


def _match_glob_prefix(path: Path, pattern: str) -> bool:
    if pattern.startswith("**/"):
        return path.match(pattern[3:])
    return False


def _is_blocked_rel_path(path: Path, blocked_root: Path) -> bool:
    try:
        path.relative_to(blocked_root)
        return True
    except ValueError:
        return False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
