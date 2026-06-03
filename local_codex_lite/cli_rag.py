"""``rag`` subcommands: build and query the workspace retrieval index.

Split out of ``cli.py``; re-exported from ``cli`` for backwards compatibility.
"""

from __future__ import annotations

import argparse

from .cli_utils import (
    console,
    workspace_root,
)
from .cli_utils import (
    print_retrieved_rag_context as _print_retrieved_rag_context,
)
from .config import load_config
from .rag import (
    RagProviderError,
    format_retrieved_context,
)
from .rag import (
    index_workspace as rag_index_workspace,
)
from .rag import (
    query_index as rag_query_index,
)


def cmd_rag_index(args: argparse.Namespace) -> int:
    root = workspace_root()
    cfg = load_config(root)
    try:
        info = rag_index_workspace(root, cfg)
    except RagProviderError as exc:
        console.print("[red]RAG index failed[/red]")
        console.print(str(exc))
        return 1
    console.print(f"RAG index built: {info.index_path}")
    console.print(f"Provider: {info.provider}")
    console.print(f"Chunks: {info.chunk_count}")
    console.print(f"Files: {info.file_count}")
    return 0


def cmd_rag_query(args: argparse.Namespace) -> int:
    root = workspace_root()
    cfg = load_config(root)
    try:
        retrieved = rag_query_index(args.query, root, cfg, top_k=args.top_k)
    except RagProviderError as exc:
        console.print("[red]RAG query failed[/red]")
        console.print(str(exc))
        return 1
    if not retrieved:
        console.print("No RAG matches found.")
        return 0
    _print_retrieved_rag_context(format_retrieved_context(retrieved, cfg.rag.max_context_chars))
    return 0
