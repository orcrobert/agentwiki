---
type: meta
summary: "Append-only activity log. Add entries only with `python3 _system/wiki.py log` so every header stays parseable."
---
# Log

Format: `## [YYYY-MM-DD] op | title` followed by bullets. Ops: setup, ingest, capture, query, save, lint, refactor, schema, note, project, worklog, issue, idea, explain, study.
Tip: `grep "^## \[" wiki/log.md | tail -5` shows the last five operations.
