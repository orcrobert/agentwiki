---
name: wiki-explain
description: Write or refresh plain-language explainer docs for the current project in the personal wiki — overview, architecture with diagram, module walkthroughs, key flows, decisions, glossary and a presentation pitch with likely Q&A — grounded in the actual code. Use when the user wants to understand a codebase, explain or present a project, prepare for questions about it, or after big architectural changes.
argument-hint: "[overview | architecture | module <name> | flow <name> | decisions | glossary | pitch | all | refresh]"
allowed-tools: Bash({{WIKI_PY}} *) Bash(git log *) Bash(git rev-parse *) Bash(graphify update *) Bash(graphify query *) Bash(graphify path *) Bash(graphify explain *)
---
<!-- installed by agent-wiki-kit from {{VAULT}}/_system/global — edit there, then run `wiki.py install-global` -->

# Explain a project (for understanding and presenting)

The reader is the user: smart, but maybe hasn't touched this code in months, and may have to present it to a professor, interviewer or teammate. Optimize for **understanding and saying it out loud**, not API reference.

## 0. Orient
- `{{WIKI_PY}} project which --path "$PWD"` (register first via the wiki-log skill if needed). `{{WIKI_PY}} context --cwd "$PWD"` shows existing explainers.
- Read broadly before writing: README, manifests (package.json, pyproject, go.mod…), entry points, directory tree, config, the main modules, tests (they reveal intent), `git log --oneline | head -50` for history. For big repos, delegate per-area reading to Explore subagents and ask them for: purpose, key files, data flow, surprises.
- **Optional code graph**: only if `{{WIKI_PY}} graphify` exits 0 (the user opted in). Otherwise skip this step without mentioning it.
  - `graphify update .` builds or refreshes `graphify-out/` from the code alone (a local parse, no LLM, seconds). If it refuses because the graph shrank after a refactor, add `--force`.
  - Read `graphify-out/GRAPH_REPORT.md` to decide *what to read*. God nodes are roughly the core abstractions (overview, glossary). Communities are module candidates and the boxes of the architecture diagram. Surprising connections are worth a sentence or a decision entry.
  - For flows: `graphify path "<entry>" "<sink>"`. For one component's neighbours: `graphify explain "<name>"`. For "what touches X": `graphify query "<question>"`.
  - The graph says where to look; **citations still come from files you opened**. Edges marked INFERRED are guesses. If `graphify-out/` isn't gitignored in this repo, tell the user rather than editing their `.gitignore`.

## 1. Pick docs (default `all` on first run = overview + architecture + pitch, then modules for the 3–6 most important parts)
| kind | slug | content |
|---|---|---|
| overview | `overview` | problem, users, what it does, how to run it, tech stack and why |
| architecture | `architecture` | components and how data flows between them; a ```mermaid diagram; where state lives; external services |
| module | `<area>` | one major part: responsibility, key files, how it works step by step, gotchas |
| flow | `<name>-flow` | one end-to-end path (e.g. "request → generate → mix → stream"), as numbered steps with file refs |
| decision | `decisions` | why it's built this way: choices, alternatives rejected, trade-offs (use the log/issues as evidence) |
| glossary | `glossary` | project-specific terms in plain words |
| pitch | `pitch` | 30-second and 2-minute spoken versions; demo script; 8–12 likely questions with crisp answers (incl. "what would you do differently", "hardest bug" — draw on issue pages); with a code graph, note that `graphify-out/graph.html` is an interactive structure map worth showing |

Create: `{{WIKI_PY}} new doc <slug> --parent <project> --kind <kind> --title "<Project>: <Title>" --summary "<≤200 chars>"` (the project prefix is added for you). If the page exists, update it in place.

## 2. Write
- Lead each page with 2–3 sentences a non-expert understands; then go deeper. Concrete over abstract: name the files, show a 5–15 line excerpt only when it is the clearest explanation.
- Ground every claim in the code: `` `path/to/file.py:42` ``. Never describe code you didn't read; mark uncertainty (*Unverified:*).
- Set `code_rev:` to `git rev-parse --short HEAD` (lint later flags docs that fell far behind the code).
- Link related docs, issues (`[[project-issue-slug]]`) and general concepts in the wiki (`{{WIKI_PY}} search "<topic>"`).
- Remove template comments; delete empty sections.

## 3. Close
`{{WIKI_PY}} index` → `{{WIKI_PY}} lint` (fix errors you caused) → `{{WIKI_PY}} worklog "Explainers: <which>" --session <id> --did "…"`. Report the pages as paths, plus the 3 questions you'd expect when presenting and where the answers are.

`refresh`: for each existing doc, `git log --oneline <code_rev>..HEAD -- <its files>`; update what changed, bump `code_rev`, set `status: outdated` only if you can't verify. With the optional code graph, run `graphify update .` first and compare `GRAPH_REPORT.md` communities with the architecture doc's components. New or merged communities often mean the architecture changed even where no explainer file did.
