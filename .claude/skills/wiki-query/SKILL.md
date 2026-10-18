---
name: wiki-query
description: Answer questions from the personal wiki with citations (projects, issues, work logs, course notes, concepts, sources) — find pages via hot cache, index and search, read them and their sources, answer with clear separation of sourced facts, synthesis and gaps, and offer to file valuable answers back. Use for any question about topics, people, sources or ideas this wiki covers ("what do we know about…", "compare…", "summarize…", "what did X say about…", "how does A relate to B"), even if the user doesn't mention the wiki.
argument-hint: "<question>"
allowed-tools: Bash(python3 _system/wiki.py *)
---

# Query the wiki

Goal: a trustworthy answer grounded in the compiled wiki — and a wiki that gets better from the question.

1. **Orient.** For project questions ("what did I do on X", "how did we fix Y") start from the project hub, its work log and issues (`wiki.py context --project <slug>`). For study questions start from the area hub and its notes. Read `wiki/hot.md`; read `wiki/overview.md` for broad questions. Find candidates by scanning `wiki/index.md`, and run `python3 _system/wiki.py search "<terms>"` with 2–3 phrasings (always, when status says the index is large). If `qmd` is installed (CLI or MCP), also run a `qmd query` for semantic matches.
2. **Read.** Read candidate pages fully; follow `[[links]]` 1–2 hops where relevant. Check key claims on their source pages. Open `raw/` only when exact wording or numbers matter.
3. **Answer.**
   - Lead with the direct answer, then support it. Cite wiki pages as `[[page]]` and key facts with their `[[src-…]]` pages.
   - Separate what sources say, what the wiki synthesizes, and your own inference. Surface confidence levels and contested claims.
   - State plainly what the wiki does not cover. Anything from general knowledge is labeled "Not from the wiki:".
   - Pick the format that fits: prose, comparison table, timeline, brief. Slides (Marp), JSON Canvas or charts only when asked.
4. **File back.** If the answer is a non-trivial synthesis (comparison, analysis, decision, newly discovered connection), offer in one line to save it. If accepted, follow `.claude/skills/wiki-save/SKILL.md`.
5. **Capture gaps.** If the question exposed a gap, add it to `wiki/questions.md` (open question or source to find).
6. **Log.** `python3 _system/wiki.py log query "<question, ≤80 chars>" --note "pages: <slugs consulted>"`. No commit needed for a pure query; the session-end autosave covers it. Query entries are how lint later sees which areas get asked about.
