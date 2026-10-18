@AGENTS.md

## Claude Code specifics
- Vault skills in `.claude/skills/`: `/wiki-study`, `/wiki-ingest`, `/wiki-query`, `/wiki-save`, `/wiki-lint`, `/wiki-capture`, `/wiki-status`; manual-only: `/wiki-schema`, `/wiki-setup`. User-wide skills (installed from `_system/global/skills/` by `wiki.py install-global`): `/wiki-log`, `/wiki-idea`, `/wiki-explain`, `/wiki-recall`. Use them instead of improvising. If a skill and AGENTS.md disagree, AGENTS.md wins; point out the conflict.
- Vault hooks (`.claude/settings.json`): SessionStart injects status + hot cache; PreToolUse blocks changes to existing files in `raw/`; SessionEnd autosaves a commit. Global hooks (`~/.claude/settings.json`, via `wiki.py hook …`) do project context / work-log reminder / auto-log in every other repo and stay silent inside this vault. If a hook blocks you, change your approach; don't work around it.
- After editing `_system/global/*`, run `python3 _system/wiki.py install-global` so the installed copies match. After editing `_system/wiki.py` or hooks, run `selftest`.
- `.claude/rules/wiki-pages.md` loads when you touch `wiki/`; `.claude/rules/raw-sources.md` when you touch `raw/`.
- Use AskUserQuestion for setup interviews, ingest checkpoints and study quizzes. For wide reads (full lint, explaining a large repo), delegate cluster reads to Explore subagents.
- Install `kepano/obsidian-skills` (BOOTSTRAP Phase 4) so you write correct Obsidian Markdown, Bases and Canvas.
