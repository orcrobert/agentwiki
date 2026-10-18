---
paths:
  - "wiki/**"
---

# Wiki page conventions

These rules keep the wiki consistent for the human (Obsidian) and for tools (`wiki.py lint`, `index`, Bases). If a rule seems wrong, propose a change via /wiki-schema instead of silently deviating.

## Page types
| type | lives in | is for | `kind` / key fields |
|---|---|---|---|
| project | `projects/<p>/<p>.md` (hub) | one repo/product: what it is, pitch, key decisions | `status` active/paused/done/archived · `repo` (abs path, list ok) · `stack` |
| worklog | `projects/<p>/<p>-log.md` | dated entries of what was done and why | written by `wiki.py worklog` |
| ideas | `projects/<p>/<p>-ideas.md` | ideas the human voiced; `- [ ]` checklist | written by `wiki.py idea` |
| issue | `projects/<p>/issues/` | a bug, obstacle or gotcha: symptom, cause, fix, lessons | `status` open/fixed/workaround/wontfix · `severity` low…critical · `resolved` |
| doc | `projects/<p>/docs/` | explainers grounded in code | `kind` overview/architecture/module/flow/decision/setup/glossary/pitch · `code_rev` |
| area | `learning/<a>/<a>.md` (hub) | a course, book, skill, research question or topic | `kind` course/book/skill/research/topic · `term` |
| note | `learning/<a>/notes/` | lecture/chapter/reading/session notes | `kind` lecture/seminar/lab/reading/chapter/video/session/summary · `date` |
| assignment | `learning/<a>/assignments/` | homework, exam, project, deadline | `kind` · `status` todo/doing/submitted/graded/missed · `due` · `grade` |
| concept | `concepts/` | an idea, technique, tool or theory, shared across areas/projects | `areas` · `confidence` · `sources` |
| source | `sources/` (`src-` prefix) | one page per raw file: what it says, how reliable | `raw` · `kind` · `reliability` · `areas` |
| synthesis | `syntheses/` | filed-back answers, comparisons, analyses, decisions | `kind` · `question` · `areas` |

Special pages (`index`, `log`, `hot`, `overview`, `questions`) have `type: meta` in `wiki/` root.

## Membership (how hubs list their pages)
- Child pages (worklog, ideas, issue, doc, note, assignment) have `parent: "[[hub-slug]]"`. `wiki.py new … --parent` sets it, prefixes the slug with the hub slug and files the page in the right folder.
- Cross-cutting pages (concept, source, synthesis) list hubs in `areas: ["[[algorithms-2]]", "[[halcyon]]"]`.
- `wiki.py index` rebuilds each hub's member list between `<!-- wiki:hub:start/end -->`. Don't edit inside the markers.

## Creating pages
- Always via the tool: `wiki.py project add`, `worklog`, `issue`, `idea`, or `new <type> <slug> --title … [--parent …] [--kind …] [--due …] --summary …`. Then delete the template's guidance comments and drop sections that stay empty.
- Concepts: create when central to a note/source, recurring in ≥2 places, or asked for. Otherwise plain text, and add it to "Wanted pages" in questions.md if it recurs.
- No empty placeholders. Size: 150–1,200 words; split bigger pages (e.g. explainers per module).

## Filenames, titles, aliases
- Slug = filename: lowercase kebab-case ASCII, unique across the vault. Hub slugs are short and stable (`halcyon`, `algorithms-2`). H1 = the readable title.
- Alternative names and abbreviations go in `aliases`. Rename only with `wiki.py rename old new`.

## Frontmatter
Common: `type`, `summary` (≤200 chars, plain sentence, no links: it is the index/hub line), `status`, `created`, `updated` (YYYY-MM-DD), `tags` (few, kebab). Quote wikilinks in frontmatter: `parent: "[[x]]"`, `sources: ["[[src-a]]"]`. After a substantive edit: `wiki.py touch <slug>`.

## Evidence
- **Project pages** (issues, docs, hub): ground claims in code with `` `path/file.ext:line` ``, commit shas, or work-log entries (`[[p-log]]`). Never describe code you didn't read; mark guesses *Hypothesis:* / *Unverified:*.
- **Concept and synthesis pages**: every factual sentence cites a source or note page inline: `… is O(n log n) ([[algorithms-2-l03-sorting]]).` or `([[src-clrs-ch2]], p. 31)`. Lint warns if a concept/synthesis cites nothing.
- **Notes** are first-hand records (the human's lecture/reading notes): they don't need citations except for quotes, but set `sources:` when made from a source page.
- Confidence (concept/synthesis): **high** = ≥2 independent reliable sources agree · **medium** = one reliable source (default) · **low** = weak source, heavy inference or open contradiction.
- Quotes: ≤2 sentences, verbatim, with locator. Don't paste copyrighted slides/book text wholesale.

## Work logs, issues, ideas
- Work log entry = outcome + why + key files + follow-ups. One per session (the tool merges by `--session`). Humans may edit entries; agents append, never rewrite old entries (fix mistakes with a new line `- **Correction:** …`).
- Issue lifecycle: open → fixed/workaround/wontfix. When resolving, fill Cause, Fix (commit), Lessons and set `resolved`. Reopen (status back to open + dated note) instead of duplicating.
- Ideas: only what the human said, in their words. Done → tick `[x]`; dropped → move under `## Dropped` with a reason.

## Conflicts and change over time
- Unresolved conflict: `> [!warning] Contradiction (YYYY-MM-DD)` callout citing both sides, `status: contested`, entry in questions.md.
- Resolved by newer evidence: rewrite, and add under `## History`: `- YYYY-MM-DD — "old claim" ([[src-old]]) superseded by ([[src-new]]): reason.`
- Code changed under an explainer: update it and bump `code_rev`, or set `status: outdated`.
- Whole page obsolete: `status: superseded` + `superseded_by: "[[new]]"`; keep the page.

## Links and structure
- Link the first mention of anything that has a page (`[[slug|display]]`). No dangling links.
- `## Related` lists 2–6 links with the relation (part of / depends on / example of / contrasts with / used in).
- Diagrams: ```mermaid blocks. Images: `![[file.png]]` from `raw/assets/`.
- Flashcards: `Question :: Answer`, one per line, under `## Flashcards` (concepts) or `## Review questions` (notes).

## Special pages
- `hot.md` ≤30 lines: Focus · Recently changed · Active threads · Next up. Rewrite, don't append.
- `overview.md`: what's in the wiki now (active projects, current courses/books), each with a one-line status and link.
- `questions.md`: Open questions · Contested claims · Wanted pages · Sources to find · Ideas & someday (non-project ideas).
- `index.md` and `log.md`: only via `wiki.py index` / `wiki.py log`.
