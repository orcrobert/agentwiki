---
name: wiki-save
description: File valuable work from the current conversation back into the wiki as a synthesis page (answer, comparison, analysis, decision, timeline, thesis) with its reasoning, evidence, alternatives and citations, then link it into related pages, index, log and hot cache. Use when the user says save/file/keep/crystallize this, "add this to the wiki", or accepts an offer to file an answer back.
argument-hint: "[title]"
allowed-tools: Bash(python3 _system/wiki.py *) Bash(git add *) Bash(git commit *)
---

# Save a synthesis back to the wiki

Explorations compound only if they're filed. A good synthesis page records not just the conclusion but **why**, so the reasoning can be reused or revised later instead of re-derived.

1. **Dedupe.** `python3 _system/wiki.py search "<topic>"`. If a synthesis already answers the same question, update it (note the change under its History) instead of creating a new one.
2. **Create.** `python3 _system/wiki.py new synthesis <slug> --title "<Title>" --kind <answer|comparison|analysis|decision|timeline|thesis> --question "<the question>" --summary "<≤200 chars>"`.
3. **Write** from this conversation:
   - Answer — direct, a few sentences.
   - Analysis — table/timeline/argument; facts cite `[[src-…]]` pages; inferences marked as such.
   - Evidence — the strongest supporting points, cited.
   - Alternatives & counterarguments — what was considered and rejected, and why.
   - Assumptions & confidence — what would change the answer; set `confidence` honestly.
   - `sources:` — source pages and wiki pages consulted (quoted wikilinks).
   Delete the template comments.
4. **Integrate.** Set `areas:` to the related learning areas/projects. Link the synthesis from 2+ related concept, note or doc pages (`## Related`). If the conversation surfaced new *sourced* facts that belong on concept pages, add them there with citations. Project-specific decisions belong on the project instead: a doc of kind `decision` (wiki-explain skill) or the hub's Key decisions. New open questions → `questions.md`. Update `overview.md` if the thesis moved.
5. **Close.** `python3 _system/wiki.py touch <changed slugs>` → `index` → `lint` (fix errors) → `log save "<Title>" --created <slug> --updated <slugs>` → rewrite `hot.md` → `git add -A && git commit -m "wiki: save | <Title>"`. Report the new page as a link.
