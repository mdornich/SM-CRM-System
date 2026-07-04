# SM-CRM-System

Transcript-to-relationship-intelligence pipeline. Obsidian vault = evidence archive,
Twenty CRM = operational layer, this pipeline = extraction/planning layer.
Spec: `docs/architecture.md` (governs). Source contract: `docs/build-prompt.md`.

## Local CI (canonical — run before declaring work complete)

```bash
source .venv/bin/activate
ruff check . && ruff format --check . && pytest
```

## Ground rules

- The Twenty fork at `~/Documents/GitHub/twenty` is read-only reference; local backend runs on port **3002** (not 3000).
- Never modify `~/GitHub/980labsOS` from this repo.
- No outbound-send code anywhere (test-enforced). No delete methods on `CRMAdapter`.
- Mock LLM is the default provider; do not wire real Anthropic calls into tests.
- `output/` is generated state — never commit its contents.
