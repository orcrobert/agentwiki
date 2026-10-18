---
name: wiki-status
description: Report the wiki's current state — page counts by type, pending sources, last lint, uncommitted changes, recent activity, hot cache, open questions — and recommend the single best next action. Use when the user asks for status, an overview of the wiki, what's pending, what to do next, or "where were we".
allowed-tools: Bash(python3 _system/wiki.py *) Bash(git status *) Bash(git log *)
---

# Wiki status

1. Run `python3 _system/wiki.py status` and `python3 _system/wiki.py lint --exit-zero` (only report counts unless there are errors).
2. Skim `wiki/questions.md` for the top open questions and contested claims.
3. Report in ≤14 lines: active projects (last work-log date, open issues), deadlines in the next 14 days and overdue ones, size (pages by type, sources pending), health (lint errors/warnings, last lint, uncommitted changes), recent activity, what's hot. `python3 _system/wiki.py project list` gives the project table.
4. Recommend one next action, in this priority order: overdue/near deadline → fix lint errors → commit uncommitted work → ingest pending sources → lint if due → resolve a contested claim → find a source for the top open question.
