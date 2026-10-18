## Personal wiki (all projects)
My knowledge wiki lives at `{{VAULT}}` (Obsidian vault; rules in its AGENTS.md). Tool: `{{WIKI_PY}} <command>`.
- **Session start:** a hook injects `<project-wiki-context>` for the current repo: open issues, recent work, explainers. Use it; before debugging an error, check its issues and run `{{WIKI_PY}} search "<error>"`.
- **Log work automatically** (skill `wiki-log`): after meaningful work (a feature, fix, refactor, investigation, decision), append ONE short work-log entry per session with `worklog … --session <id>`. Outcome and why, not a diff. Skip trivia. A Stop hook reminds you; don't fight it.
- **Issues automatically:** any non-trivial bug, obstacle or gotcha gets an issue page (`issue …`); when solved, set `status` and fill Cause / Fix / Lessons.
- **Ideas only when I say so** (skill `wiki-idea`): "idea:", "for later", "would be nice" → `idea "…"`. Never invent ideas on my behalf.
- **Explain code for me** (skill `wiki-explain`) when I ask to understand/present a project, or after big architectural changes.
- Never put secrets, tokens or private data into the wiki. Don't commit the wiki from project repos manually; hooks autosave it.
