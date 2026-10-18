---
name: wiki-setup
description: One-time bootstrap of this personal wiki — preflight checks, git, verification, installing the user-wide project hooks/skills, personalization interview (projects, courses, books), Obsidian configuration and a first project + learning area — by executing _system/BOOTSTRAP.md phase by phase. Manual-only.
disable-model-invocation: true
allowed-tools: Bash(python3 _system/wiki.py *) Bash(git init *) Bash(git add *) Bash(git commit *) Bash(git status *)
---

# Set up the wiki

Read `_system/BOOTSTRAP.md` in full, then execute it phase by phase, starting at the first phase whose boxes aren't all checked (setup can span sessions).

- Tick each checkbox in BOOTSTRAP.md as you complete it, and commit at the end of every phase (`wiki: setup | phase N`).
- Meet each phase's acceptance criteria before moving on; if one can't be met, stop and explain.
- Use AskUserQuestion for the domain interview. Never overwrite a file the human already has (e.g. an existing `.obsidian/app.json`) without showing the change first.
- When all phases are done, give the human a 5-line summary of how to use the wiki day to day.
