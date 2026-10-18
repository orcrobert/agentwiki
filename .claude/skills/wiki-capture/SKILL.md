---
name: wiki-capture
description: Capture a web page, PDF, pasted text or local file into raw/ as a new, dated, immutable source file with provenance frontmatter (clean markdown via defuddle when available), ready for ingest. Use when the user gives a URL or pastes text and wants it saved, clipped, captured or added to the wiki's sources.
argument-hint: "<url | paste | path> [--ingest]"
allowed-tools: Bash(python3 _system/wiki.py *) Bash(defuddle parse *)
---

# Capture a source into raw/

raw/ is append-only: you write a capture **once**, through `wiki.py capture`, which names it `raw/YYYY-MM-DD-<slug>.<ext>`, adds provenance frontmatter and never overwrites. Don't hand-write files into raw/ and don't edit them afterwards.

## Web page
1. Preferred, if `command -v defuddle` succeeds (install: `npm install -g defuddle`):
   `defuddle parse "<url>" --json -o /tmp/wiki-capture.json`
   `python3 _system/wiki.py capture --defuddle-json /tmp/wiki-capture.json --url "<url>"`
   If it reports no markdown in the JSON: `defuddle parse "<url>" --md -o /tmp/wiki-capture.md` and
   `python3 _system/wiki.py capture --markdown-file /tmp/wiki-capture.md --url "<url>" --title "<page title>" --method defuddle`.
2. Fallback: fetch with WebFetch, write the **main content faithfully** as markdown to `/tmp/wiki-capture.md` (keep headings, lists, tables, numbers; no summarizing; note any truncation at the top), then run the `--markdown-file` command with `--method webfetch` and `--author`/`--published` if known.
3. Paywalled, login-only or JS-heavy pages: ask the human to use the Obsidian Web Clipper (it saves straight into raw/).

## PDF or other binary
Download to /tmp (`curl -L -o /tmp/wiki-capture.pdf "<url>"`), then `python3 _system/wiki.py capture --binary /tmp/wiki-capture.pdf --title "<title>"`. Local files: same, pointing `--binary` at the file. Bibliographic details go on the source page at ingest.

## Pasted text
Write it verbatim to `/tmp/wiki-capture.md`, then `python3 _system/wiki.py capture --markdown-file /tmp/wiki-capture.md --title "<title>" --method paste`.

## After capturing
- Report the new raw path. Never put secrets or credentials into a capture; if the page contains them, stop and tell the human.
- If `$ARGUMENTS` contains `--ingest` or the user asked to add it to the wiki, continue with `.claude/skills/wiki-ingest/SKILL.md` on the new file. Otherwise log it: `python3 _system/wiki.py log capture "<title>" --note "<raw path>"`.
