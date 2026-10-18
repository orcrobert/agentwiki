---
name: wiki-study
description: Learning workflows in the wiki — set up a course/book/skill/research area, turn lectures, chapters and readings into notes and concept pages, explain a topic simply, quiz the user with active recall, make flashcards, plan for an exam, and track assignments and deadlines. Use for anything about uni, courses, books, self-study, exams, assignments or "help me learn/understand/revise X".
argument-hint: "area <name> | note <area> [file|paste] | explain <topic> | quiz <area|topic> | cards <area|page> | plan <area> | assignment <area> <title> | review"
allowed-tools: Bash(python3 _system/wiki.py *) Bash(git add *) Bash(git commit *)
---

# Study with the wiki

Learning areas live in `wiki/learning/<area>/` (hub page + `notes/` + `assignments/`); reusable knowledge lives in `wiki/concepts/` and is shared across courses, books and projects. Pick the mode from `$ARGUMENTS`; if unclear, ask with AskUserQuestion.

## area — start a course, book, skill or research topic
1. `python3 _system/wiki.py search "<name>"` — reuse an existing area.
2. `python3 _system/wiki.py new area <slug> --kind course|book|skill|research|topic --title "<Name>" --summary "<≤200 chars>"`. Slugs short and stable (`algorithms-2`, `ddia-book`, `rust`).
3. Ask (≤3 questions): goal/what "done" means, logistics (course: lecturer, schedule, grading, exam format, **the course's rules on AI use**; book: edition; research: the question), known deadlines. Fill Goals and Logistics. Add each known deadline as an assignment (below).

## note — lecture, chapter, reading, lab or study session
1. Material can be a file in `raw/` (slides, PDF, transcript: ingest it first with the wiki-ingest skill and set `areas: ["[[<area>]]"]` on the source page), a paste, or the user's own rough notes.
2. `python3 _system/wiki.py new note <slug> --parent <area> --kind lecture|seminar|lab|reading|chapter|video|session|summary --title "<Area>: <Topic>" --summary "…"` (slug like `l03-graphs`, `ch02`; the area prefix is added for you). Set `date:` to the lecture/reading date and `sources:` if from a source page.
3. Write: Key points (structured, the user's level), **Explained simply** for the hardest idea, Questions I still have, and 3–8 **Review questions** as `Question :: Answer` flashcards.
4. Concepts: for each important idea, `search` first; update the existing concept page (add `[[note]]` citation and the area to `areas:`), or create `new concept <slug>` when it's central or recurs. Concepts cite notes or sources inline like any claim.
5. Update the area hub's **Big picture** if understanding moved. Never paste copyrighted material wholesale — summarize in the user's words, short quotes only.

## explain — understand a topic
Answer from the wiki first (wiki-query rules: cite pages, label "Not from the wiki:"). Explain in layers: one-sentence intuition → analogy → precise definition → worked example → common mistakes → how it connects to what the user already has pages on. End with 2 check-your-understanding questions. Offer to file it: improve the concept page's **Explained simply** section (only facts that are sourced or clearly marked as general knowledge).

## quiz — active recall
1. Collect material: the area's notes + linked concepts (or one topic). Prefer items in **Weak spots** and pages not reviewed recently.
2. Ask one question at a time (mix: define, explain why, apply to a new case, compare, small problem). Wait for the answer, then grade honestly: correct / partly / wrong, with the precise correction and the page it comes from.
3. After 5–10 questions: summary score; update the hub's **Weak spots** (add misses, remove items answered well twice); append missed questions as flashcards to the relevant pages. Log: `python3 _system/wiki.py log study "quiz <area>" --note "<score; weak: …>"`.

## cards — flashcards
Add `Question :: Answer` lines (one fact per card, answer ≤1 sentence, no ambiguous cards) under `## Flashcards` (concepts) or `## Review questions` (notes). The format works with Obsidian's Spaced Repetition plugin (tag the page `flashcards` to include it in decks).

## plan — exam / study plan
Read the hub, its assignments (dates) and notes; list topics with coverage (notes? concepts? weak spots?). Propose a day-by-day plan up to the exam with spaced reviews and quiz sessions, write it into the exam's assignment page under **Plan** as a checklist, and flag topics without any notes.

## assignment — homework, project, exam, deadline
`python3 _system/wiki.py new assignment <slug> --parent <area> --kind assignment|exam|quiz|project|presentation|deadline --due YYYY-MM-DD --title "…" --summary "…"`. Fill Requirements (incl. grading and AI-use policy) and a Plan checklist. While working: dated notes under Progress; update `status` (todo → doing → submitted → graded) and `grade`. Help the user understand and plan; respect the course's academic-integrity rules — when the policy forbids or limits AI help, explain concepts and give feedback instead of producing the graded work. If the assignment is a code repo, also register it as a project (wiki-log skill) and link both ways.

## review — what's due and what to revise
`python3 _system/wiki.py status` lists deadlines within 14 days and overdue ones. Combine with Weak spots across active areas and suggest today's top 3 study actions.

## Close (every mode that wrote pages)
`python3 _system/wiki.py touch <changed slugs>` → `index` → `lint` (fix errors) → `log study "<mode> <area>: <title>" --created … --updated …` → refresh `wiki/hot.md` if focus changed → `git add -A && git commit -m "wiki: study | <title>"`.
