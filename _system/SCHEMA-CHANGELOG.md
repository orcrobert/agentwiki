# Schema changelog

One entry per approved schema change (date · change · rationale). Maintained by /wiki-schema.

- 2026-10-16 · v1 · Initial generic LLM-wiki kit.
- 2026-10-18 · v2 · Repurposed from a generic research wiki into a personal dev + learning wiki: new types project/worklog/ideas/issue/doc (projects) and area/note/assignment (learning); removed `entity`; generated hub member lists; per-type enums; `wiki.py project|worklog|idea|issue|context|hook|commit|install-global`; user-wide hooks + skills (wiki-log, wiki-idea, wiki-explain, wiki-recall) so agents in every repo log work and issues automatically; new vault skill wiki-study. Rationale: the human wanted automatic project notes, code explainers to present from, and study tooling — not a general research wiki.
