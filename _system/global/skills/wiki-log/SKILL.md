---
name: wiki-log
description: Record work in the personal wiki for the current project — append a work-log entry (what was done and why), create or update issue pages for bugs and obstacles, register the repo as a project on first use. Use after meaningful work in any repo, when a Stop hook asks for a work-log entry, when a bug is found or fixed, or when the user says log/note/record this.
argument-hint: "[what to log]"
allowed-tools: Bash({{WIKI_PY}} *)
---
<!-- installed by agent-wiki-kit from {{VAULT}}/_system/global — edit there, then run `wiki.py install-global` -->

# Log project work to the wiki

Vault: `{{VAULT}}` · tool: `{{WIKI_PY}}` (abbreviated `W` below). The user reads this later to remember what happened, so write for a human, not a machine.

## 0. Which project?
`W project which --path "$PWD"`. If none:
- register once: `W project add <slug> --title "<Name>" --summary "<what it is, ≤200 chars>" --repo "<git toplevel>" --stack <lang> <framework> …` (slug: short kebab, e.g. `halcyon`). Then open the hub page it prints and fill **What it is** and **How to explain it** from the README/code (3–6 lines, plain language).
- if the user doesn't want this repo tracked: `W project ignore <path>`.

## 1. Work-log entry (once per session, merged by session id)
```
W worklog "<outcome, ≤80 chars>" --session <session id from the context/Stop hook> \
  --did "<what changed and why>" [--did "…"] --files <key paths> \
  [--issue <issue-slug>] [--next "<follow-up / open end>"] [--note "<gotcha, decision>"]
```
- Calling it again with the same `--session` adds an **Update** to the same entry, so log incrementally without spam.
- Good: "Switched mixer to streaming — fixes 40 s latency; chunk size 4096 tuned by ear". Bad: "Edited mixer.py".
- Record decisions with their reason (`--note "Chose SQLite over Postgres: single user, zero ops"`). Big decisions also go in the hub's **Key decisions**.
- Don't log trivia (typo fixes, formatting) unless that's all the session did.

## 2. Issues (automatic for anything non-trivial)
Create one when a bug, failing build, confusing behaviour, environment problem or gotcha cost real time or could recur:
`W issue "<short title>" --summary "<symptom in one line>" --severity low|medium|high|critical [--status fixed]`
Then edit the printed page: **Symptom** (short error text), **Context** (`path:line`, versions), **Cause** (mark guesses *Hypothesis:*), **Fix / workaround** (commit sha), **Lessons**. When solved later: set `status: fixed` (or `workaround`/`wontfix`), `resolved: YYYY-MM-DD`, fill Cause/Fix, `W touch <slug>`. Reference it from the work log with `--issue <slug>`.
Before creating, check for an existing one: `W search "<keywords>"` — reopen/update instead of duplicating.

## 3. Rules
- Pages are edited directly (Edit tool on the printed path); create pages only via `W`. After edits: `W touch <slug>` and `W index`.
- No secrets, tokens, customer data or private personal data in the wiki.
- Don't commit the vault yourself; the SessionEnd hook autosaves (`W commit "<msg>"` if the user asks).
