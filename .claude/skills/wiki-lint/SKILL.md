---
name: wiki-lint
description: Health-check and repair the LLM wiki — deterministic checks (broken links, orphans, frontmatter, index drift, duplicates, changed or pending sources) plus a semantic review (contradictions, superseded claims, unsourced statements, confidence miscalibration, missing pages and cross-references, research gaps). Use when the user asks to lint, audit, clean up or check the wiki, after batch ingests, or when status says a lint is due.
argument-hint: "[quick | full | <folder-or-slug>]"
allowed-tools: Bash(python3 _system/wiki.py *) Bash(git log *) Bash(git add *) Bash(git commit *)
---

# Lint the wiki

Two layers: cheap **deterministic** checks that never need judgment, then a **semantic** review where you read pages. Fix what is safe; queue what needs the human.

## 1. Deterministic pass
Run `python3 _system/wiki.py lint`. Fix mechanically:
- `index-stale` → `wiki.py index`. `missing-field` / `bad-value` / `bad-date` → edit frontmatter.
- `broken-link` → retarget if the intended page is obvious (check aliases with `wiki.py search`); otherwise turn it into plain text and add it to "Wanted pages".
- `bad-filename` → `wiki.py rename`. `orphan` → link it from the most related page's `## Related`.
- `possible-duplicate` / `alias-collision` → propose a merge to the human; don't merge unasked.
- `bad-parent` → set `parent:` to the right hub (search for it); `overdue` → ask the human for the real status of the assignment; `doc-maybe-stale` → offer `/wiki-explain refresh` in that repo.
- `raw-changed` → tell the human (raw files should never change); offer to re-ingest.
- `pending-raw` → list them; offer to ingest.
Re-run until there are 0 errors.

## 2. Semantic pass
Scope from `$ARGUMENTS`:
- `quick` (default): pages changed since the last lint — find the date with `grep "^## \[.*\] lint" wiki/log.md | tail -1`, then `git log --since=<date> --name-only --format= -- wiki/ | sort -u` — plus their direct neighbours.
- `full`: every page. Above ~60 pages, work cluster by cluster (by folder or by hub page) and delegate cluster reads to Explore subagents that return findings, keeping your own context for fixing.
- a folder or slug: just that area.

Look for:
- **Contradictions** between pages, and claims **superseded** by newer sources that still read as current.
- **Unsourced or weakly sourced** claims; inferences not marked as inferences; evidence borrowed across entities.
- **Confidence miscalibration** against the rubric in `.claude/rules/wiki-pages.md`.
- **Missing pages** (concepts/entities mentioned on ≥2 pages without one) and **missing cross-references** between closely related pages.
- **Stale stubs**, pages over ~1,500 words that should split, summaries that no longer match the body.
- **Projects**: issues `open` for >30 days with work-log entries suggesting they were fixed; work-log entries mentioning bugs without an issue page; hubs whose "What it is" is empty; ideas pages that duplicate each other.
- **Learning**: notes without linked concepts; concepts used in ≥2 areas missing `areas:`; areas with assignments but no notes; empty Weak spots after quizzes.
- **Gaps**: important questions the wiki can't answer; areas with one source only. Check recent `query` entries in the log for what gets asked.

## 3. Fix and queue
- Fix directly: add links and `## Related` entries, add citations that already exist on source pages, add contradiction callouts, move superseded claims to `## History`, recalibrate `status`/`confidence`, refresh summaries.
- Queue for the human: merges, deletions, contested claims that need a judgment call.
- Update `questions.md`: open questions, contested claims, wanted pages, and **sources to find** with suggested search queries.

## 4. Close
1. Write `_system/reports/lint-<YYYY-MM-DD>.md`: scope, counts before/after, fixes made, decisions needed, suggested next sources.
2. `wiki.py touch` changed pages → `wiki.py index` → `wiki.py lint` (0 errors) → `wiki.py log lint "<quick|full|scope>" --updated <slugs> --note "<n fixes; m decisions queued>"`.
3. Rewrite `hot.md`; `git add -A && git commit -m "wiki: lint | <scope>"`.
4. Report: what you fixed, what needs the human's decision, and the top 3 sources worth adding next.
