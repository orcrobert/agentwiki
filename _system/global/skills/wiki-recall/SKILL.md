---
name: wiki-recall
description: Look things up in the personal wiki from any repo — past issues and fixes, earlier decisions, what was done on a project, notes from courses/books, concepts. Use before debugging an error that might have happened before, when the user asks "did we…", "how did I fix…", "what do I know about…", "where were we on <project>", or wants a status of a project.
argument-hint: "<question or error text>"
allowed-tools: Bash({{WIKI_PY}} *)
---
<!-- installed by agent-wiki-kit from {{VAULT}}/_system/global — edit there, then run `wiki.py install-global` -->

# Recall from the wiki

1. Search: `{{WIKI_PY}} search "<terms>" -n 8` with 2–3 phrasings (error text, component name, concept). `{{WIKI_PY}} project list` for project overviews; `{{WIKI_PY}} context --project <slug>` for a project's open issues and recent work.
2. Read the hits (paths under `{{VAULT}}/wiki/`); follow `[[links]]` one hop. For history: `grep -n "<term>" {{VAULT}}/wiki/projects/<slug>/<slug>-log.md`.
3. Answer with what the wiki says, citing pages as `[[slug]]`; label anything else as "Not from the wiki:". Say plainly when the wiki has nothing.
4. If this turned up a fix that worked again, add a line to that issue's **Lessons** (and `touch` it).
