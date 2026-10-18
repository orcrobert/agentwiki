---
name: wiki-schema
description: Propose and apply reviewed changes to the wiki's conventions — AGENTS.md, page rules, templates, skills, wiki.config.json — based on recurring corrections, lint findings and how the domain has evolved, then migrate existing pages. Manual-only.
argument-hint: "[what to change, or empty to review]"
disable-model-invocation: true
allowed-tools: Bash(python3 _system/wiki.py *) Bash(git log *) Bash(git add *) Bash(git commit *)
---

# Evolve the schema

The schema is what turns a generic model into a disciplined wiki maintainer, so it changes deliberately: evidence → proposal → approval → migration.

1. **Gather evidence.** The user's request (`$ARGUMENTS`); corrections the human made in this or recent sessions; human edits to wiki pages (`git log --format='%h %an %s' -- wiki/ | head -40`, commits not starting with `wiki:`); recurring lint warnings and `_system/reports/`; log notes; domain drift visible in `overview.md`.
2. **Propose minimal diffs** to the relevant files (AGENTS.md, `.claude/rules/*.md`, `_system/templates/*`, a skill, `_system/wiki.config.json`), each with a one-line rationale and the evidence. Prefer sharpening an existing rule to adding a new one. Keep AGENTS.md ≤ ~80 lines and the CLAUDE.md + imports total under 200 lines; push detail into rules or skills.
3. **Wait for explicit approval** per change. Apply only what's approved.
4. **Migrate.** If the change affects existing pages (new required field, new type, renamed kind), update `wiki.config.json` so lint enforces it, run `wiki.py lint` to list violations, and migrate in batches of ≤25 pages with approval. Bump `schema_version` in the config.
5. **Record.** Append to `_system/SCHEMA-CHANGELOG.md` (date, change, rationale), `python3 _system/wiki.py log schema "<summary>"`, run `python3 _system/wiki.py selftest`, and commit `wiki: schema | <summary>`.
