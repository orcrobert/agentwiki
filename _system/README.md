# Your personal dev + learning wiki — quick guide

Agents write it, you read it in Obsidian. Two halves:
- **Projects**: every repo you work in gets a hub with a work log, issues, ideas and plain-language explainers of the code.
- **Learning**: courses, books, skills and research, with notes, assignments, concepts, flashcards and quizzes.

## First run
1. `cd` into this vault, run `claude`, accept the trust prompt, type `/wiki-setup`.
2. Setup installs user-wide hooks and skills (`python3 _system/wiki.py install-global`) so agents in **all your repos** write here.

## What happens automatically (in any repo)
| When | What |
|---|---|
| A session starts in a tracked repo | The agent gets the project's open issues, recent work and explainers as context |
| The agent finishes a turn after ≥3 edits | A hook asks it to write one work-log entry (merged per session) |
| The agent hits a real bug or obstacle | It files an issue page (symptom, cause, fix, lessons) |
| The session ends | Unsummarized edits are auto-logged; the vault autosaves a git commit |
| First session in an untracked repo | The agent offers to register it (or `wiki.py project ignore <path>`) |

## You ask for
| You want to… | Say / run |
|---|---|
| Save an idea | "idea: …" or `/wiki-idea …` (only you add ideas) |
| Understand / present a project | `/wiki-explain` (overview, architecture, modules, flows, decisions, glossary, pitch + Q&A) |
| Remember how something was fixed | `/wiki-recall <error or topic>` |
| Start a course/book/skill | `/wiki-study area <name>` |
| Turn a lecture or chapter into notes | `/wiki-study note <area>` (drop slides into `raw/` first) |
| Get quizzed / make flashcards / exam plan | `/wiki-study quiz|cards|plan <area>` |
| Track an assignment or exam | `/wiki-study assignment <area> <title>` |
| Add an article/paper | Web Clipper into `raw/`, or `/wiki-capture <url> --ingest` |
| Ask anything | Just ask, or `/wiki-query …`; keep good answers with `/wiki-save` |
| See what's going on | `/wiki-status` · open `wiki/dashboard.base` |
| Health check | `/wiki-lint` weekly, `/wiki-lint full` monthly |

## Rules of the road
- `raw/` is append-only. You may edit any wiki page; the agents respect your edits.
- Everything is in git: `git log --oneline`, `git revert <commit>` to undo.
- Keep the vault out of iCloud/Dropbox sync. Back up with a private git remote.

## Turning things off
- Work-log reminders: `WIKI_REMIND=0` in your environment, or raise `remind_min_edits` in `_system/wiki.config.json`.
- One repo: `python3 _system/wiki.py project ignore <path>`.
- Everything user-wide: `python3 _system/wiki.py install-global --uninstall` (restores nothing else; backups `~/.claude/*.wiki-backup-*` exist).
- Vault autosave: `WIKI_AUTOSAVE=0`.
- Optional graphify support (off by default): `python3 _system/wiki.py graphify on|off`.

## Tooling
`python3 _system/wiki.py --help`. After editing `_system/wiki.py`: `selftest`. After editing `_system/global/*`: `install-global`.
