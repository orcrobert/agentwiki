---
name: wiki-idea
description: Save a future idea the user voices for the current (or a named) project into the personal wiki's ideas list. Use when the user says "idea:", "for later", "would be cool", "someday", "remember this idea", or /wiki-idea. Never invent ideas on the user's behalf.
argument-hint: "<the idea> [--project slug]"
allowed-tools: Bash({{WIKI_PY}} *)
---
<!-- installed by agent-wiki-kit from {{VAULT}}/_system/global — edit there, then run `wiki.py install-global` -->

# Save an idea

1. Take the idea from `$ARGUMENTS` or the user's words. Keep their wording; tighten it to one line. Add context the user gave (why, constraints) as details.
2. `{{WIKI_PY}} idea "<one-line idea>" [--detail "<why / notes>"] [--project <slug>]` — without `--project` it uses the repo you're in. If the idea isn't about a project (e.g. a study or life idea), ask which project, or put it in `{{VAULT}}/wiki/questions.md` under "Ideas & someday".
3. Confirm in one line with the page path. Don't start implementing it unless asked.
