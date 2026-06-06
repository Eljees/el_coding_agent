# Configuration

Config lives at `.local-codex-lite/config.yaml` (create it with `init`). A
starting template is `config.example.yaml`. Use `config show` to print the
effective, **redacted** config.

## LLM

```yaml
llm:
  base_url: "http://localhost:8015/v1"
  model: "qwen25-coder-14b-awq"
  api_key: "local-not-needed"
  temperature: 0.1
  max_tokens: 2048
  timeout: 120.0
  retries: 2
  suggest_timeout_seconds: 120  # hard deadline for the whole suggest-commands stage
```

`timeout` bounds a single HTTP request; `suggest_timeout_seconds` bounds the
post-apply "suggest commands" stage as a whole (retries and context-shrinking
attempts multiply the per-request timeout). On deadline the suggestions are
skipped (`commands_skipped.json` in the run dir) and the run still succeeds.

### Named profiles

Define alternative endpoints/models and select one per invocation with
`--profile <name>` on `run` / `preview` / `ask` / `review`:

```yaml
llm_profiles:
  fast:
    base_url: "http://localhost:8100/v1"
    model: "qwen25-coder-7b"
    max_tokens: 1024
  review:
    base_url: "http://localhost:8200/v1"
    model: "qwen25-coder-32b-awq"
    timeout: 300.0
```

## Workspace

```yaml
workspace:
  root: "."
  max_file_bytes: 120000
  include_globs: ["**/*.py", "**/*.md", "**/*.toml", "**/*.yaml", "**/*.json"]
  exclude_globs: [".git/**", ".venv/**", "__pycache__/**", ".local-codex-lite/**", ...]
```

`max_file_bytes` caps how much of any one file is fed to the model. The
exclude globs keep caches, secrets and noisy folders out of context.

## Safety

```yaml
safety:
  require_apply_flag: true     # writes need --apply
  require_exec_flag: true      # commands need --exec
  allow_sensitive_read: false  # block reading .env / *secret* / *token*
  max_patch_attempts: 4        # repair budget per run
  smoke_run_default: false     # post-apply smoke run executes generated code; opt-in
  smoke_timeout_seconds: 10    # per-script smoke deadline; long-lived scripts pass
```

See [safety](safety.md). Override the patch budget for one run with
`--max-patch-attempts`; enable the smoke run for one run with `--smoke`.

## RAG

```yaml
rag:
  provider: "keyword"          # the default, zero-dependency provider
  enabled: true
  store_dir: ".local-codex-lite/rag/keyword"
  top_k: 8
  chunk_chars: 1800
  overlap_chars: 250
  max_context_chars: 12000
```

The optional `[rag]` extra (`chromadb`, `sentence-transformers`) enables a
vector provider. Without it, the keyword provider works out of the box.
