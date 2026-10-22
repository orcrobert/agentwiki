---
name: wiki-lint
description: Health-check and repair the LLM wiki — deterministic checks (broken links, orphans, frontmatter, index drift, duplicates, changed or pending sources) plus a semantic review (contradictions, superseded claims, unsourced statements, confidence miscalibration, missing pages and cross-references, research gaps). Use when the user asks to lint, audit, clean up or check the wiki, after batch ingests, or when status says a lint is due.
argument-hint: "[quick | full | graph | <folder-or-slug>]"
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
- `graph`: `full`, plus graph-assisted discovery (below). Only if `python3 _system/wiki.py graphify` exits 0. If it doesn't, say graphify is off (`wiki.py graphify on` enables it) and run `full`.

**Graph-assisted discovery (`graph` only).** Obsidian's graph shows the links you already wrote; a graphify graph also finds pages that are about related things but never link.
1. From the vault root, build or refresh the graph over `wiki/` with the graphify skill (`/graphify wiki`, or `/graphify wiki --update` when `graphify-out/graph.json` exists). Markdown needs semantic extraction, so this costs tokens; tell the human before a first full build of a large wiki. Never use `--obsidian`, `--wiki` or `add`: the graph's own pages must not land in the vault.
2. `python3 _system/wiki.py graphify gaps` lists page pairs the graph connects that don't link each other (either way), and clusters over ≥3 pages that have no concept or synthesis page.
3. Treat each line as a **lead**: read both pages and add a link only when a reader would actually want it, with a reason in the surrounding sentence. Clusters with no concept page are candidates for missing pages (ask or queue as usual). Discard INFERRED-only pairs that don't hold up.
4. Also skim `graphify-out/GRAPH_REPORT.md` "Surprising connections" for cross-area links (a course concept used in a project). These are the links this wiki exists to make.

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
1. Write `_system/reports/lint-<YYYY-MM-DD>.md`: scope, counts before/after, fixes made, decisions needed, suggested next sources (for `graph`: how many gap leads were accepted vs discarded).
2. `wiki.py touch` changed pages → `wiki.py index` → `wiki.py lint` (0 errors) → `wiki.py log lint "<quick|full|scope>" --updated <slugs> --note "<n fixes; m decisions queued>"`.
3. Rewrite `hot.md`; `git add -A && git commit -m "wiki: lint | <scope>"`.
4. Report: what you fixed, what needs the human's decision, and the top 3 sources worth adding next.
