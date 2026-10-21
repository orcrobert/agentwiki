#!/usr/bin/env python3
"""wiki.py — deterministic tooling for an LLM-maintained Obsidian wiki.

Python 3.8+, standard library only. Run from anywhere; the vault root is the
parent of the _system/ folder that contains this file.

Commands
  status [--hook]            counts, pending sources, last lint, git state, hot cache
  pending                    raw files not yet ingested (computed, never a flag)
  search QUERY [-n N]        BM25 search over wiki pages (title/aliases/summary/body)
  new TYPE SLUG --title T    create a page from _system/templates/TYPE.md
  touch SLUG...              set `updated:` to today on the given pages
  index [--check]            rebuild the generated region of wiki/index.md
  lint [--json] [--exit-zero] [--fix]
                             structural health check (no LLM); exit 1 on errors
  rename OLD NEW [--dry-run] rename a page and rewrite every link to it
  log OP TITLE [...]         append a correctly formatted entry to wiki/log.md
  capture ...                write a new, dated, immutable file into raw/
  project add|which|list|ignore
                             register repos as projects; map a directory to its project
  worklog TITLE [...]        append a dated entry to a project's work log
  idea TEXT [...]            append an idea to a project's ideas page
  issue TITLE [...]          create an issue page in a project
  context [--cwd DIR]        compact project context (used by the global SessionStart hook)
  hook EVENT                 global Claude Code hooks: session-start | stop | session-end
  commit MSG                 git add -A + commit inside the vault (no-op when clean)
  install-global [--uninstall] [--dry-run]
                             install user-level hooks, skills and CLAUDE.md block
  graphify [on|off]          optional graphify integration: show status (exit 0 = ready), or toggle it
  graphify gaps [--graph G]  from a graph built over wiki/: unlinked page pairs + clusters without a concept page
  selftest                   run the built-in test-suite in a temp vault
"""

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("WIKI_ROOT") or SYSTEM_DIR.parent).resolve()

KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FM_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
WIKILINK_RE = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
FENCE_RE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.S | re.M)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
COMMENT_RE = re.compile(r"<!--.*?-->|%%.*?%%", re.S)
H1_RE = re.compile(r"^#[ \t]+(.+?)\s*$", re.M)
LOG_HEADER_RE = re.compile(r"^## \[(\d{4}-\d{2}-\d{2})\] ([a-z][a-z0-9-]*) \| (.+)$")
INDEX_START = "<!-- wiki:index:start -->"
INDEX_END = "<!-- wiki:index:end -->"
HUB_START = "<!-- wiki:hub:start -->"
HUB_END = "<!-- wiki:hub:end -->"
SESSION_RE = re.compile(r"^%% session: (\S+) %%$", re.M)
ATTACHMENT_EXTS = {
    "png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "avif", "heic", "pdf",
    "mp3", "wav", "m4a", "ogg", "flac", "mp4", "webm", "mov", "mkv",
    "base", "canvas", "csv", "json", "txt", "html", "epub", "docx", "xlsx", "pptx",
}
SKIP_DIRS_ANYWHERE = {"node_modules", "graphify-out"}  # tool output, never wiki pages or sources


def today():
    return _dt.date.today().isoformat()


def load_config(root=None):
    root = Path(root or ROOT)
    cfg_path = root / "_system" / "wiki.config.json"
    if not cfg_path.exists():
        cfg_path = SYSTEM_DIR / "wiki.config.json"
    with open(cfg_path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Minimal YAML-subset frontmatter parser (scalars, inline lists, block lists)
# ---------------------------------------------------------------------------

def _unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        inner = v[1:-1]
        if v[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        else:
            inner = inner.replace("''", "'")
        return inner
    return v


def _split_inline_list(s):
    """Split the inside of `[a, "b, c", [[d]]]` into items, respecting quotes/brackets."""
    items, buf, quote, depth = [], [], None, 0
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == "[":
            depth += 1
            buf.append(ch)
        elif ch == "]":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            items.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        items.append(tail)
    return [i for i in items if i != ""]


def parse_frontmatter(text):
    """Return (fm_dict or None, fm_raw or None, body, warnings)."""
    m = FM_RE.match(text)
    if not m:
        return None, None, text, []
    raw = m.group(1)
    body = text[m.end():]
    data, warnings = {}, []
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        km = re.match(r"^([A-Za-z_][\w\-]*)\s*:\s*(.*)$", line)
        if not km or line[0] in " \t":
            i += 1
            continue
        key, val = km.group(1), km.group(2).strip()
        # strip trailing comment only for unquoted scalars
        if val and val[0] not in "\"'[" and " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        if val == "":
            j = i + 1
            items = []
            while j < len(lines) and (lines[j].startswith((" ", "\t")) or not lines[j].strip()):
                lm = re.match(r"^\s*-\s*(.*)$", lines[j])
                if lm:
                    items.append(lm.group(1).strip())
                j += 1
            if items:
                for it in items:
                    if it.startswith("[[") and it.endswith("]]"):
                        warnings.append("unquoted wikilink in frontmatter list '%s' (Obsidian needs quotes)" % key)
                data[key] = [_unquote(it) for it in items]
            else:
                data[key] = ""
            i = j
            continue
        if val in ("|", "|-", ">", ">-", "|+", ">+"):
            j = i + 1
            block = []
            while j < len(lines) and (lines[j].startswith((" ", "\t")) or not lines[j].strip()):
                block.append(lines[j].strip())
                j += 1
            data[key] = (" " if val.startswith(">") else "\n").join(block).strip()
            i = j
            continue
        if val.startswith("[") and val.endswith("]") and not val.startswith("[["):
            items = _split_inline_list(val[1:-1])
            for it in items:
                if it.startswith("[[") and it.endswith("]]"):
                    warnings.append("unquoted wikilink in frontmatter list '%s' (Obsidian needs quotes)" % key)
            data[key] = [_unquote(it) for it in items]
        else:
            if val.startswith("[[") and val.endswith("]]"):
                warnings.append("unquoted wikilink in frontmatter field '%s' (Obsidian needs quotes)" % key)
            data[key] = _unquote(val)
        i += 1
    return data, raw, body, warnings


def yaml_quote(s):
    s = "" if s is None else str(s)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_fm_field(text, key, value_literal):
    """Set `key: value_literal` inside the frontmatter of text (adds the key if missing)."""
    m = FM_RE.match(text)
    if not m:
        return "---\n%s: %s\n---\n%s" % (key, value_literal, text)
    raw = m.group(1)
    pat = re.compile(r"^%s\s*:.*$" % re.escape(key), re.M)
    if pat.search(raw):
        raw = pat.sub(lambda _m: "%s: %s" % (key, value_literal), raw, count=1)
    else:
        raw = raw.rstrip("\n") + "\n%s: %s" % (key, value_literal)
    return "---\n" + raw + "\n---\n" + text[m.end():]


# ---------------------------------------------------------------------------
# Vault model
# ---------------------------------------------------------------------------

def strip_code(text):
    """Remove fenced code, inline code and comments (HTML and Obsidian %%) before link parsing."""
    text = FENCE_RE.sub("", text)
    text = COMMENT_RE.sub("", text)
    return INLINE_CODE_RE.sub("", text)


def link_target(inner):
    """`[[a/b#h|alias]]` -> 'a/b'. Handles escaped pipes inside tables."""
    t = inner.replace("\\|", "|").split("|", 1)[0]
    t = t.split("#", 1)[0].split("^", 1)[0]
    return t.strip().rstrip("\\").strip()


def extract_links(text):
    out = []
    for m in WIKILINK_RE.finditer(strip_code(text)):
        tgt = link_target(m.group(2))
        if tgt:
            out.append((tgt, bool(m.group(1))))
    return out


def fm_links(fm):
    out = []
    if not fm:
        return out
    for v in fm.values():
        vals = v if isinstance(v, list) else [v]
        for item in vals:
            if isinstance(item, str):
                for m in WIKILINK_RE.finditer(item):
                    tgt = link_target(m.group(2))
                    if tgt:
                        out.append((tgt, False))
    return out


class Page:
    def __init__(self, path, root):
        self.path = path
        self.rel = path.relative_to(root).as_posix()
        self.slug = path.stem
        text = path.read_text(encoding="utf-8", errors="replace")
        self.text = text
        self.fm, self.fm_raw, self.body, self.fm_warnings = parse_frontmatter(text)
        h1 = H1_RE.search(strip_code(self.body))
        self.h1 = h1.group(1).strip() if h1 else None
        self.body_links = extract_links(self.body)
        self.prop_links = fm_links(self.fm)

    @property
    def type(self):
        return (self.fm or {}).get("type", "") if isinstance((self.fm or {}).get("type", ""), str) else ""

    @property
    def title(self):
        return self.h1 or (self.fm or {}).get("title") or self.slug

    def field(self, key, default=""):
        return (self.fm or {}).get(key, default)

    def list_field(self, key):
        v = (self.fm or {}).get(key, [])
        if isinstance(v, list):
            return v
        return [v] if v else []

    def link_field(self, key):
        """Slugs (lowercase) linked from a frontmatter field: `parent: "[[x]]"` -> ['x']."""
        out = []
        for item in self.list_field(key):
            m = WIKILINK_RE.search(str(item))
            t = link_target(m.group(2)) if m else str(item).strip()
            if t:
                out.append(t.split("/")[-1].lower())
        return out

    @property
    def parent(self):
        p = self.link_field("parent")
        return p[0] if p else ""


class Vault:
    def __init__(self, root=None):
        self.root = Path(root or ROOT).resolve()
        self.cfg = load_config(self.root)
        self.wiki_dir = self.root / self.cfg["wiki_dir"]
        self.raw_dir = self.root / self.cfg["raw_dir"]
        exclude = set(self.cfg["exclude_dirs"])
        self.md_files, self.other_files = [], []
        for dirpath, dirnames, filenames in os.walk(self.root):
            rel_dir = Path(dirpath).relative_to(self.root)
            dirnames[:] = [d for d in dirnames
                           if not (rel_dir == Path(".") and d in exclude)
                           and not d.startswith(".") and d not in SKIP_DIRS_ANYWHERE]
            for fn in filenames:
                p = Path(dirpath) / fn
                if fn.lower().endswith(".md"):
                    self.md_files.append(p)
                else:
                    self.other_files.append(p)
        self.stems = defaultdict(list)  # lower stem -> [paths]
        for p in self.md_files:
            self.stems[p.stem.lower()].append(p)
        self.files_by_name = defaultdict(list)
        for p in self.other_files:
            self.files_by_name[p.name.lower()].append(p)
        self.pages = []
        if self.wiki_dir.exists():
            for p in sorted(self.md_files):
                try:
                    p.relative_to(self.wiki_dir)
                except ValueError:
                    continue
                self.pages.append(Page(p, self.root))
        self.by_slug = {pg.slug.lower(): pg for pg in self.pages}

    # -- helpers --------------------------------------------------------
    def resolve(self, target):
        t = target.replace("\\", "/").strip()
        if t.lower().endswith(".md"):
            t = t[:-3]
        base = t.split("/")[-1]
        ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
        if ext in ATTACHMENT_EXTS:
            if (self.root / t).exists():
                return self.root / t
            hits = self.files_by_name.get(base.lower())
            return hits[0] if hits else None
        if "/" in t and (self.root / (t + ".md")).exists():
            return self.root / (t + ".md")
        hits = self.stems.get(base.lower())
        return hits[0] if hits else None

    def special(self, name):
        return self.wiki_dir / (name + ".md")

    def raw_files(self):
        out = []
        if not self.raw_dir.exists():
            return out
        ignore = self.cfg.get("raw_ignore", [])
        for dirpath, dirnames, filenames in os.walk(self.raw_dir):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS_ANYWHERE]
            for fn in filenames:
                p = Path(dirpath) / fn
                rel_in_raw = p.relative_to(self.raw_dir).as_posix()
                if fn.startswith("."):
                    continue
                if any(rel_in_raw == ig or (ig.endswith("/") and rel_in_raw.startswith(ig)) or fn == ig
                       for ig in ignore):
                    continue
                out.append(p)
        return sorted(out)

    def source_raw_refs(self):
        """Map normalized raw path -> [source pages that reference it]."""
        refs = defaultdict(list)
        for pg in self.pages:
            if pg.type != "source":
                continue
            for r in pg.list_field("raw"):
                refs[normalize_raw_ref(r)].append(pg)
        return refs

    def pending(self):
        refs = self.source_raw_refs()
        out = []
        for p in self.raw_files():
            rel = p.relative_to(self.root).as_posix()
            if rel.lower() not in refs:
                out.append(rel)
        return out

    def log_entries(self):
        p = self.special("log")
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            m = LOG_HEADER_RE.match(line)
            if m:
                out.append((m.group(1), m.group(2), m.group(3), line))
        return out

    def content_pages(self):
        specials = set(self.cfg["special_pages"])
        return [pg for pg in self.pages if pg.slug not in specials and pg.type != "meta"]

    def tdef(self, t):
        return self.cfg["types"].get(t, {})

    def enums_for(self, t):
        e = dict(self.cfg.get("enums", {}))
        e.update(self.tdef(t).get("enums", {}))
        return e

    def hubs(self, t=None):
        return [pg for pg in self.content_pages()
                if self.tdef(pg.type).get("hub") and (t is None or pg.type == t)]

    def members(self, hub):
        """Pages owned by a hub (`parent`) or tagged with it (`areas`)."""
        return [pg for pg in self.content_pages() if pg is not hub
                and (pg.parent == hub.slug or hub.slug in pg.link_field("areas"))]

    def children(self, hub, t):
        return [pg for pg in self.content_pages() if pg.parent == hub.slug and pg.type == t]

    def find_project(self, path):
        """Project hub whose `repo` contains path (longest match wins), or None."""
        target = os.path.realpath(os.path.expanduser(str(path)))
        best, best_len = None, -1
        for hub in self.hubs("project"):
            for r in hub.list_field("repo"):
                r = str(r).strip()
                if not r:
                    continue
                rp = os.path.realpath(os.path.expanduser(r))
                if (target == rp or target.startswith(rp.rstrip(os.sep) + os.sep)) and len(rp) > best_len:
                    best, best_len = hub, len(rp)
        return best

    def project_by_slug(self, slug):
        pg = self.by_slug.get(str(slug).lower())
        return pg if pg is not None and pg.type == "project" else None


def strip_md(s):
    s = s.strip()
    return s[:-3] if s.lower().endswith(".md") else s


def clean_raw_ref(r):
    """'./raw/x.md', '"raw/x.md"', '[[raw/x.md]]' -> 'raw/x.md' (case preserved)."""
    r = str(r).strip()
    m = WIKILINK_RE.search(r)
    if m:
        r = link_target(m.group(2))
    r = r.replace("\\", "/")
    while r.startswith("./"):
        r = r[2:]
    return r


def normalize_raw_ref(r):
    return clean_raw_ref(r).lower()


def sha256_short(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def git(root, *args, check=False):
    try:
        r = subprocess.run(["git", "-C", str(root)] + list(args), capture_output=True, text=True, timeout=20)
        if check and r.returncode != 0:
            raise RuntimeError(r.stderr.strip())
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def kebab(s, max_words=10, max_len=70):
    s = s.lower()
    s = re.sub(r"['’`]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    words = [w for w in s.split("-") if w][:max_words]
    out = "-".join(words)[:max_len].strip("-")
    return out or "untitled"


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------

def _safe_title(pg):
    return pg.title.replace("|", "-").replace("]", ")").replace("[", "(")


def worklog_dates(pg):
    return re.findall(r"^## (\d{4}-\d{2}-\d{2})", pg.body, re.M)


def last_activity(v, hub):
    dates = [d for wl in v.children(hub, "worklog") for d in worklog_dates(wl)]
    return max(dates) if dates else ""


def _index_line(pg, cfg, v=None):
    title = _safe_title(pg)
    summary = str(pg.field("summary", "")).strip() or "(no summary)"
    meta = []
    status = pg.field("status", "")
    if v is not None and pg.type == "project":
        n_open = sum(1 for i in v.children(pg, "issue") if i.field("status") == "open")
        meta.append(status or "?")
        if n_open:
            meta.append("%d open issue(s)" % n_open)
        la = last_activity(v, pg)
        if la:
            meta.append("last log %s" % la)
        return "- [[%s|%s]] — %s · %s" % (pg.slug, title, summary, " · ".join(meta))
    if v is not None and pg.type == "area":
        meta.append(str(pg.field("kind", "")))
        if status and status != "active":
            meta.append(status)
        todo = [a for a in v.children(pg, "assignment") if a.field("status") in ("todo", "doing")]
        if todo:
            meta.append("%d open assignment(s)" % len(todo))
        meta.append("%d note(s)" % len(v.children(pg, "note")))
        return "- [[%s|%s]] — %s · %s" % (pg.slug, title, summary, " · ".join(m for m in meta if m))
    if pg.type == "source":
        for k in ("kind", "published"):
            v = pg.field(k, "")
            if v and isinstance(v, str):
                meta.append(v)
    else:
        n = len(pg.list_field("sources"))
        if n:
            meta.append("%d src" % n)
        conf = pg.field("confidence", "")
        if conf and conf != "medium":
            meta.append("conf: %s" % conf)
    if status and status != "active":
        if status == "superseded" and pg.field("superseded_by"):
            meta.append("superseded → %s" % pg.field("superseded_by"))
        else:
            meta.append(status)
    upd = pg.field("updated", "")
    if upd:
        meta.append("upd %s" % upd)
    tail = (" · " + " · ".join(meta)) if meta else ""
    return "- [[%s|%s]] — %s%s" % (pg.slug, title, summary, tail)


def build_index_region(v):
    cfg = v.cfg
    lines = [INDEX_START]
    start = [v.by_slug[s] for s in cfg.get("start_here", []) if s in v.by_slug]
    content = v.content_pages()
    hidden = set(cfg.get("index_hidden_types", []))
    n_hidden = sum(1 for pg in content if pg.type in hidden)
    lines.append("_%d pages (%d of them listed on their project/area hub). Generated by "
                 "`python3 _system/wiki.py index` — edit pages, not this list._" % (len(content), n_hidden))
    if start:
        lines += ["", "## Start here"] + [_index_line(pg, cfg) for pg in start]
    groups = defaultdict(list)
    for pg in content:
        if pg.type not in hidden:
            groups[pg.type or "untyped"].append(pg)
    order = list(cfg.get("index_order", [])) + sorted(t for t in groups if t not in cfg.get("index_order", []))
    for t in order:
        if not groups.get(t):
            continue
        heading = cfg.get("index_headings", {}).get(t, t.capitalize())
        pgs = sorted(groups[t], key=lambda p: p.title.lower())
        lines += ["", "## %s (%d)" % (heading, len(pgs))] + [_index_line(pg, cfg, v) for pg in pgs]
    lines.append(INDEX_END)
    return "\n".join(lines)


def _hub_line(pg):
    bits = []
    if pg.type == "issue":
        bits = [str(pg.field("status", "")), "sev %s" % pg.field("severity", "?")]
    elif pg.type == "assignment":
        bits = ["due %s" % pg.field("due", "?"), str(pg.field("status", ""))]
    elif pg.type in ("doc", "note"):
        bits = [str(pg.field("kind", ""))]
        if pg.field("date", ""):
            bits.append(str(pg.field("date")))
        if pg.field("status", "") in ("stub", "outdated", "superseded"):
            bits.append(str(pg.field("status")))
    elif pg.type == "worklog":
        d = worklog_dates(pg)
        bits = ["%d entries" % len(d)] + (["last %s" % d[-1]] if d else [])
    elif pg.type == "ideas":
        n = len(re.findall(r"^- \[ \]", pg.body, re.M))
        bits = ["%d open" % n]
    summary = str(pg.field("summary", "")).strip()
    tail = " · ".join(b for b in bits if b)
    return "- [[%s|%s]] — %s%s" % (pg.slug, _safe_title(pg), summary, (" · " + tail) if tail else "")


def build_hub_region(v, hub):
    members = v.members(hub)
    lines = [HUB_START, "_Generated by `wiki.py index` from each page's `parent`/`areas` — don't edit by hand._"]
    by_type = defaultdict(list)
    for pg in members:
        by_type[pg.type].append(pg)
    order = [t for t, _h in v.cfg.get("hub_sections", [])]
    heads = dict(v.cfg.get("hub_sections", []))
    for t in order + sorted(t for t in by_type if t not in order):
        pgs = by_type.get(t)
        if not pgs:
            continue
        if t == "issue":
            rank = {"open": 0, "workaround": 1, "fixed": 2, "wontfix": 3}
            pgs.sort(key=lambda p: (rank.get(p.field("status"), 9), p.title.lower()))
        elif t == "assignment":
            pgs.sort(key=lambda p: (str(p.field("due", "9999")), p.title.lower()))
        elif t == "note":
            pgs.sort(key=lambda p: (str(p.field("date", "") or p.field("created", "")), p.slug))
        else:
            pgs.sort(key=lambda p: p.title.lower())
        lines += ["", "### %s" % heads.get(t, t.capitalize())] + [_hub_line(pg) for pg in pgs]
    if not by_type:
        lines += ["", "_Nothing filed here yet._"]
    lines.append(HUB_END)
    return "\n".join(lines)


def current_region(text, start, end):
    s, e = text.find(start), text.find(end)
    if s == -1 or e == -1:
        return None
    return text[s:e + len(end)]


def stale_hubs(v):
    out = []
    for hub in v.hubs():
        cur = current_region(hub.text, HUB_START, HUB_END)
        if cur is not None and cur != build_hub_region(v, hub):
            out.append(hub)
    return out


def rebuild_hubs(v):
    n = 0
    for hub in stale_hubs(v):
        cur = current_region(hub.text, HUB_START, HUB_END)
        hub.text = hub.text.replace(cur, build_hub_region(v, hub))
        hub.path.write_text(hub.text, encoding="utf-8")
        n += 1
    return n


def reindex_quietly():
    """Refresh hub regions and index.md after a command changed membership."""
    v = Vault()
    rebuild_hubs(v)
    v = Vault()
    path = v.special("index")
    region = build_index_region(v)
    cur = current_index_region(path)
    if path.exists() and cur is not None and cur != region:
        path.write_text(set_fm_field(path.read_text(encoding="utf-8").replace(cur, region), "updated", today()),
                        encoding="utf-8")


def current_index_region(path):
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    s, e = text.find(INDEX_START), text.find(INDEX_END)
    if s == -1 or e == -1:
        return None
    return text[s:e + len(INDEX_END)]


def cmd_index(args):
    v = Vault()
    path = v.special("index")
    region = build_index_region(v)
    cur = current_index_region(path)
    if args.check:
        stale = stale_hubs(v)
        if cur == region and not stale:
            print("index: up to date")
            return 0
        print("index: STALE (%s) — run `python3 _system/wiki.py index`"
              % ", ".join((["index.md"] if cur != region else []) + [h.slug for h in stale]))
        return 1
    n_hubs = rebuild_hubs(v)
    if n_hubs:
        print("hubs: refreshed %d hub page(s)" % n_hubs)
        v = Vault()
        region = build_index_region(v)
    if cur == region:
        print("index: already up to date (%d pages)" % len(v.content_pages()))
        return 0
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if cur is None:
            m = H1_RE.search(text)
            insert_at = m.end() if m else len(text)
            text = text[:insert_at] + "\n\n" + region + "\n" + text[insert_at:]
        else:
            text = text.replace(cur, region)
    else:
        text = ("---\ntype: meta\nsummary: \"Catalog of every wiki page (generated).\"\nupdated: %s\n---\n"
                "# Index\n\n%s\n" % (today(), region))
    text = set_fm_field(text, "updated", today())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print("index: rebuilt (%d pages)" % len(v.content_pages()))
    return 0


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------

def status_of(pg):
    return str(pg.field("status", "")).strip()


def run_lint(v):
    cfg = v.cfg
    issues = []

    def add(sev, code, path, msg):
        issues.append({"severity": sev, "code": code, "path": path, "message": msg})

    types = cfg["types"]
    specials = set(cfg["special_pages"])
    citable = set(cfg.get("citable_types", ["source"]))
    max_sum = cfg.get("summary_max_chars", 200)

    # duplicate stems (ambiguous [[links]])
    for stem, paths in v.stems.items():
        if len(paths) > 1:
            rels = [p.relative_to(v.root).as_posix() for p in paths]
            in_wiki = [r for r in rels if r.startswith(cfg["wiki_dir"] + "/")]
            if in_wiki:
                add("error", "duplicate-name", in_wiki[0],
                    "file name '%s' is not unique: %s — [[links]] become ambiguous" % (stem, ", ".join(rels)))

    inbound = Counter()
    link_sources_excluded = {"index", "log", "hot"}
    alias_owner = {}
    norm_owner = defaultdict(list)

    for pg in v.pages:
        rel = pg.rel
        is_special = pg.slug in specials or pg.type == "meta"
        for w in pg.fm_warnings:
            add("warn", "frontmatter-syntax", rel, w)
        # links
        for tgt, is_embed in pg.body_links + pg.prop_links:
            hit = v.resolve(tgt)
            if hit is None:
                add("error", "broken-link", rel, "[[%s]] does not resolve to any file" % tgt)
            elif hit.suffix.lower() == ".md" and pg.slug not in link_sources_excluded and hit.stem.lower() != pg.slug.lower():
                inbound[hit.stem.lower()] += 1
        if is_special:
            continue
        # location / naming
        parent = pg.path.parent
        if parent == v.wiki_dir:
            add("warn", "wrong-folder", rel, "content pages belong in a type folder, not wiki/ root")
        if not KEBAB_RE.match(pg.slug):
            add("warn", "bad-filename", rel, "file name should be lowercase-kebab-case ASCII (use `wiki.py rename`)")
        if pg.fm is None:
            add("error", "no-frontmatter", rel, "page has no YAML frontmatter")
            continue
        t = pg.type
        if t not in types:
            add("error", "unknown-type", rel, "type '%s' is not one of %s" % (t, sorted(types)))
            continue
        tdef = types[t]
        exp_folder = v.wiki_dir / tdef["folder"]
        if tdef.get("hub"):
            exp_folder = exp_folder / pg.slug
            if HUB_START not in pg.body:
                add("warn", "hub-no-region", rel, "hub page lacks the %s … %s markers (its member list can't be generated)"
                    % (HUB_START, HUB_END))
        elif tdef.get("parent_type"):
            hub = v.by_slug.get(pg.parent) if pg.parent else None
            if hub is None:
                add("error", "bad-parent", rel, "parent must link an existing %s page, e.g. parent: \"[[slug]]\""
                    % tdef["parent_type"])
                exp_folder = None
            elif hub.type != tdef["parent_type"]:
                add("error", "bad-parent", rel, "parent [[%s]] is a %s, expected a %s" % (hub.slug, hub.type, tdef["parent_type"]))
                exp_folder = None
            else:
                exp_folder = hub.path.parent / tdef.get("subfolder", "")
        if exp_folder is not None and parent.resolve() != exp_folder.resolve():
            add("warn", "wrong-folder", rel, "type '%s' pages live in %s/" % (t, exp_folder.relative_to(v.root).as_posix()))
        if tdef.get("prefix") and not pg.slug.startswith(tdef["prefix"]):
            add("warn", "bad-filename", rel, "%s pages should start with '%s'" % (t, tdef["prefix"]))
        for key in tdef.get("required", []):
            if key not in pg.fm:
                add("error", "missing-field", rel, "missing frontmatter field '%s'" % key)
        summary = str(pg.field("summary", "")).strip()
        if not summary or summary.upper().startswith("TODO") or "{{" in summary:
            add("error", "missing-summary", rel, "summary is empty or a placeholder (index.md depends on it)")
        elif len(summary) > max_sum:
            add("warn", "long-summary", rel, "summary is %d chars (max %d)" % (len(summary), max_sum))
        for key, allowed in v.enums_for(t).items():
            val = pg.field(key, None)
            if val not in (None, "") and val not in allowed:
                add("error", "bad-value", rel, "%s: '%s' is not one of %s" % (key, val, allowed))
        for key in ("created", "updated", "ingested", "due", "date"):
            val = pg.field(key, "")
            if val and not DATE_RE.match(str(val)):
                add("warn", "bad-date", rel, "%s: '%s' is not YYYY-MM-DD" % (key, val))
        if "{{" in pg.text and "}}" in pg.text:
            add("warn", "template-placeholder", rel, "unfilled {{placeholder}} left in page")
        if "<!--" in pg.body.replace(HUB_START, "").replace(HUB_END, "") and status_of(pg) != "stub":
            add("warn", "template-guidance-left", rel, "template guidance comments left in page — delete them once sections are filled")
        if not pg.h1:
            add("warn", "no-title", rel, "no H1 title (the H1 is the human-readable title)")
        status = pg.field("status", "")
        if status == "superseded":
            sb = pg.field("superseded_by", "")
            if not sb or not WIKILINK_RE.search(str(sb)):
                add("error", "superseded-without-pointer", rel, "status superseded needs superseded_by: \"[[new-page]]\"")
        if tdef.get("needs_citation") and status != "stub":
            cites_src = False
            for tg, _e in pg.body_links:
                hit = v.by_slug.get(link_target(tg).split("/")[-1].lower())
                if hit is not None and hit.type in citable:
                    cites_src = True
                    break
            if not pg.list_field("sources") and not cites_src:
                add("warn", "unsourced", rel, "no sources in frontmatter and no citations of %s pages in body"
                    % "/".join(sorted(citable)))
        if t == "assignment" and pg.field("status") in ("todo", "doing"):
            due = str(pg.field("due", ""))
            if DATE_RE.match(due) and due < today():
                add("warn", "overdue", rel, "due %s and still '%s'" % (due, pg.field("status")))
        if t == "doc" and pg.field("code_rev", "") and status != "superseded":
            hub = v.by_slug.get(pg.parent)
            repos = hub.list_field("repo") if hub is not None else []
            if repos and os.path.isdir(os.path.expanduser(str(repos[0]))):
                rc, out = git(os.path.expanduser(str(repos[0])), "rev-list", "--count", "%s..HEAD" % pg.field("code_rev"))
                if rc == 0 and out.strip().isdigit() and int(out.strip()) >= cfg.get("doc_stale_commits", 25):
                    add("info", "doc-maybe-stale", rel, "%s commits since code_rev %s — re-check against the code"
                        % (out.strip(), pg.field("code_rev")))
        if t == "source":
            refs = pg.list_field("raw")
            if not refs:
                add("error", "source-without-raw", rel, "source page has no raw: path")
            for r in refs:
                rp = v.root / clean_raw_ref(r)
                if not rp.exists():
                    add("error", "raw-missing", rel, "raw file not found: %s" % r)
                else:
                    want = str(pg.field("raw_sha256", "")).strip()
                    if want and len(refs) == 1 and sha256_short(rp) != want:
                        add("warn", "raw-changed", rel, "raw file changed since ingest (hash mismatch) — re-ingest or investigate")
        # aliases / near-duplicates
        for a in pg.list_field("aliases"):
            key = str(a).strip().lower()
            if not key:
                continue
            if key in v.by_slug and v.by_slug[key] is not pg:
                add("warn", "alias-collision", rel, "alias '%s' equals another page's name" % a)
            if key in alias_owner and alias_owner[key] is not pg:
                add("warn", "alias-collision", rel, "alias '%s' also used by %s" % (a, alias_owner[key].rel))
            alias_owner[key] = pg
        norm = re.sub(r"[^a-z0-9]", "", pg.slug.lower().replace("src-", "", 1) if t == "source" else pg.slug.lower())
        if norm.endswith("s") and len(norm) > 4:
            norm = norm[:-1]
        norm_owner[(t == "source", norm)].append(pg)

    for (_is_src, _n), pgs in norm_owner.items():
        if len(pgs) > 1:
            add("warn", "possible-duplicate", pgs[0].rel,
                "near-identical names: %s — merge?" % ", ".join(p.rel for p in pgs))

    for pg in v.content_pages():
        if inbound[pg.slug.lower()] == 0 and not v.tdef(pg.type).get("hub"):
            add("warn", "orphan", pg.rel, "no inbound links from other wiki pages")

    # index freshness
    idx = v.special("index")
    if not idx.exists():
        add("error", "index-missing", "wiki/index.md", "index.md missing — run `wiki.py index`")
    elif current_index_region(idx) != build_index_region(v):
        add("error", "index-stale", "wiki/index.md", "generated index is stale — run `wiki.py index`")
    for hub in stale_hubs(v):
        add("error", "index-stale", hub.rel, "generated hub section is stale — run `wiki.py index`")

    # log format
    logp = v.special("log")
    if logp.exists():
        for n, line in enumerate(logp.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("## ") and not LOG_HEADER_RE.match(line):
                add("warn", "log-format", "wiki/log.md",
                    "line %d not in '## [YYYY-MM-DD] op | title' format — use `wiki.py log`" % n)
    else:
        add("error", "log-missing", "wiki/log.md", "log.md missing")

    hot = v.special("hot")
    if hot.exists():
        n = len(hot.read_text(encoding="utf-8").splitlines())
        if n > cfg.get("hot_max_lines", 40) + 10:
            add("warn", "hot-too-long", "wiki/hot.md", "hot.md has %d lines — keep it a short cache" % n)

    for rel in v.pending():
        add("info", "pending-raw", rel, "not ingested yet")

    order = {"error": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda i: (order[i["severity"]], i["code"], i["path"]))
    return issues


def cmd_lint(args):
    if args.fix:
        cmd_index(argparse.Namespace(check=False))
    v = Vault()
    issues = run_lint(v)
    counts = Counter(i["severity"] for i in issues)
    if args.json:
        print(json.dumps({"counts": counts, "issues": issues}, indent=2))
    else:
        if not issues:
            print("lint: clean ✓")
        for sev in ("error", "warn", "info"):
            group = [i for i in issues if i["severity"] == sev]
            if not group:
                continue
            print("\n%s (%d)" % (sev.upper(), len(group)))
            for i in group:
                print("  [%s] %s — %s" % (i["code"], i["path"], i["message"]))
        print("\nlint: %d error(s), %d warning(s), %d info · %d content pages"
              % (counts["error"], counts["warn"], counts["info"], len(v.content_pages())))
    if counts["error"] and not args.exit_zero:
        return 1
    return 0


# ---------------------------------------------------------------------------
# status / pending
# ---------------------------------------------------------------------------

def cmd_pending(args):
    v = Vault()
    pend = v.pending()
    if not pend:
        print("pending: none — every raw file has a source page")
        return 0
    print("pending (%d):" % len(pend))
    for rel in pend:
        try:
            mtime = _dt.date.fromtimestamp((v.root / rel).stat().st_mtime).isoformat()
        except OSError:
            mtime = "?"
        print("  %s  (added %s)" % (rel, mtime))
    return 0


def cmd_status(args):
    root = ROOT
    if not (root / "wiki").exists():
        msg = "LLM-wiki kit present but wiki/ is missing. Run /wiki-setup (see _system/BOOTSTRAP.md)."
        print(("<wiki-session-context>\n%s\n</wiki-session-context>" % msg) if args.hook else msg)
        return 0
    v = Vault()
    cfg = v.cfg
    by_type = Counter(pg.type or "untyped" for pg in v.content_pages())
    pend = v.pending()
    entries = v.log_entries()
    lint_entries = [e for e in entries if e[1] == "lint"]
    last_lint = lint_entries[-1][0] if lint_entries else None
    ingests_since = sum(1 for e in entries if e[1] == "ingest" and (last_lint is None or e[0] >= last_lint))
    rc, out = git(root, "status", "--porcelain")
    if rc == 127 or rc == 128:
        git_line = "NOT a git repository — run setup Phase 1 (version control) before any ingest"
    else:
        n = len([l for l in out.splitlines() if l.strip()])
        git_line = "clean" if n == 0 else "%d uncommitted change(s)" % n
    lines = []
    if args.hook:
        lines.append("<wiki-session-context>")
        lines.append("This folder is your personal dev + learning wiki. Follow AGENTS.md. Skills: /wiki-log /wiki-idea "
                     "/wiki-explain /wiki-recall /wiki-study /wiki-ingest /wiki-query /wiki-save /wiki-lint "
                     "/wiki-capture /wiki-status /wiki-schema /wiki-setup.")
    parts = ", ".join("%s %d" % (t, n) for t, n in sorted(by_type.items()))
    lines.append("Pages: %d (%s) · raw files: %d · pending ingest: %d"
                 % (sum(by_type.values()), parts or "none yet", len(v.raw_files()), len(pend)))
    for rel in pend[:8]:
        lines.append("  pending → %s" % rel)
    if len(pend) > 8:
        lines.append("  … and %d more (`python3 _system/wiki.py pending`)" % (len(pend) - 8))
    if last_lint:
        try:
            age = (_dt.date.today() - _dt.date.fromisoformat(last_lint)).days
        except ValueError:
            age = 0
        due = age >= cfg.get("lint_due_days", 14) or ingests_since >= cfg.get("lint_due_ingests", 10)
        lines.append("Last lint: %s (%dd ago, %d ingest(s) since)%s"
                     % (last_lint, age, ingests_since, " → lint is due (/wiki-lint)" if due else ""))
    else:
        lines.append("Last lint: never%s" % (" → run /wiki-lint" if v.content_pages() else ""))
    lines.append("Git: %s" % git_line)
    projects = [h for h in v.hubs("project") if h.field("status") == "active"]
    if projects:
        bits = []
        for h in sorted(projects, key=lambda h: last_activity(v, h), reverse=True)[:8]:
            n_open = sum(1 for i in v.children(h, "issue") if i.field("status") == "open")
            bits.append("%s (%s%s)" % (h.slug, last_activity(v, h) or "no log",
                                       ", %d open issue(s)" % n_open if n_open else ""))
        lines.append("Active projects: " + "; ".join(bits))
    horizon = (_dt.date.today() + _dt.timedelta(days=cfg.get("due_soon_days", 14))).isoformat()
    due = sorted(((str(a.field("due")), a) for a in v.content_pages()
                 if a.type == "assignment" and a.field("status") in ("todo", "doing")
                 and DATE_RE.match(str(a.field("due", ""))) and str(a.field("due")) <= horizon),
                 key=lambda x: (x[0], x[1].slug))
    for d, a in due[:6]:
        lines.append("  %s %s — %s [%s]" % ("OVERDUE" if d < today() else "due", d, a.slug, a.field("status")))
    idx = v.special("index")
    if idx.exists():
        n_idx = len(idx.read_text(encoding="utf-8").splitlines())
        if n_idx > cfg.get("index_search_threshold_lines", 300):
            lines.append("Index is %d lines: prefer `wiki.py search` (or qmd) over reading index.md whole." % n_idx)
    if entries:
        lines.append("Recent log:")
        for e in entries[-5:]:
            lines.append("  " + e[3])
    hot = v.special("hot")
    if hot.exists():
        _fm, _raw, body, _w = parse_frontmatter(hot.read_text(encoding="utf-8"))
        body_lines = [l for l in body.strip().splitlines()][: cfg.get("hot_max_lines", 40)]
        if body_lines:
            lines.append("--- wiki/hot.md ---")
            lines += body_lines
    if args.hook:
        lines.append("</wiki-session-context>")
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# search (BM25)
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(r"[^\W_]+", re.U)


def tokens(s):
    return [t for t in TOKEN_RE.findall(s.lower()) if len(t) > 1]


def cmd_search(args):
    v = Vault()
    docs = []
    for pg in v.pages:
        if pg.slug in ("index", "log"):
            continue
        aliases = " ".join(str(a) for a in pg.list_field("aliases"))
        bag = (tokens(pg.title) * 3 + tokens(pg.slug.replace("-", " ")) * 2 + tokens(aliases) * 3
               + tokens(str(pg.field("summary", ""))) * 2 + tokens(strip_code(pg.body)))
        docs.append((pg, Counter(bag), len(bag)))
    if not docs:
        print("search: wiki is empty")
        return 0
    q = tokens(args.query)
    N = len(docs)
    avgdl = sum(d[2] for d in docs) / N
    df = Counter()
    for _pg, tf, _l in docs:
        for t in set(q):
            if tf[t]:
                df[t] += 1
    k1, b = 1.2, 0.75
    scored = []
    for pg, tf, dl in docs:
        s = 0.0
        for t in q:
            if not tf[t]:
                continue
            idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * dl / max(avgdl, 1)))
        phrase = args.query.lower().strip()
        if len(phrase) > 3 and phrase in pg.text.lower():
            s *= 1.5
        if s > 0:
            scored.append((s, pg))
    scored.sort(key=lambda x: -x[0])
    if args.json:
        print(json.dumps([{"slug": pg.slug, "path": pg.rel, "title": pg.title, "type": pg.type,
                           "summary": pg.field("summary", ""), "score": round(s, 3)}
                          for s, pg in scored[: args.n]], indent=2))
        return 0
    if not scored:
        print("search: no matches for %r" % args.query)
        return 0
    for s, pg in scored[: args.n]:
        print("%6.2f  [[%s]]  (%s) %s — %s" % (s, pg.slug, pg.type or "?", pg.title, pg.field("summary", "")))
    return 0


# ---------------------------------------------------------------------------
# new / touch / rename / log / capture
# ---------------------------------------------------------------------------

def show(path):
    """Vault-relative path inside the vault, absolute path when called from another repo."""
    path = Path(path).resolve()
    try:
        Path.cwd().resolve().relative_to(ROOT)
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def create_page(v, ptype, slug, title, summary=None, kind=None, raw=None, question=None, parent=None,
                repo=None, due=None, severity=None):
    """Create a page from its template. Returns (rc, message, path)."""
    cfg = v.cfg
    if ptype not in cfg["types"]:
        return 2, "new: unknown type '%s' (have %s)" % (ptype, sorted(cfg["types"])), None
    tdef = cfg["types"][ptype]
    slug = slug.strip().lower()
    if slug.endswith(".md"):
        slug = slug[:-3]
    hub = None
    if tdef.get("parent_type"):
        if not parent:
            return 2, "new: %s pages need --parent <%s-slug>" % (ptype, tdef["parent_type"]), None
        hub = v.by_slug.get(strip_md(parent.lower()).strip("[]"))
        if hub is None or hub.type != tdef["parent_type"]:
            return 2, "new: --parent '%s' is not an existing %s page" % (parent, tdef["parent_type"]), None
        if not slug.startswith(hub.slug + "-"):
            slug = hub.slug + "-" + slug  # keeps slugs unique across the vault
    if tdef.get("prefix") and not slug.startswith(tdef["prefix"]):
        slug = tdef["prefix"] + slug
    if not KEBAB_RE.match(slug):
        return 2, "new: slug '%s' must be lowercase kebab-case ASCII, e.g. %s" % (slug, kebab(slug)), None
    if slug in v.stems:
        return 3, ("new: '%s' already exists at %s — update it instead of creating a duplicate"
                   % (slug, v.stems[slug][0].relative_to(v.root).as_posix())), v.stems[slug][0]
    tpl = v.root / "_system" / "templates" / ("%s.md" % ptype)
    if not tpl.exists():
        return 2, "new: template missing: _system/templates/%s.md" % ptype, None
    text = tpl.read_text(encoding="utf-8")
    raw_rel, raw_hash = "", ""
    if raw:
        rp = (v.root / raw).resolve()
        if not rp.exists():
            return 2, "new: raw file not found: %s" % raw, None
        raw_rel = rp.relative_to(v.root).as_posix()
        raw_hash = sha256_short(rp)
    plain = {
        "{{title}}": title.strip(),
        "{{date}}": today(),
        "{{slug}}": slug,
        "{{raw}}": raw_rel,
        "{{raw_sha256}}": raw_hash,
        "{{kind}}": kind or "other",
        "{{summary}}": (summary or "TODO: one-line summary (≤200 chars)").strip(),
        "{{question}}": (question or "").strip(),
        "{{parent}}": hub.slug if hub is not None else "",
        "{{parent_title}}": hub.title if hub is not None else "",
        "{{repo}}": repo or "",
        "{{due}}": due or "",
        "{{severity}}": severity or "medium",
    }

    def esc(x):  # values inside double-quoted YAML strings
        return x.replace("\\", "\\\\").replace('"', '\\"')
    m = FM_RE.match(text)
    fm_part, body_part = (text[:m.end()], text[m.end():]) if m else ("", text)
    for k, val in plain.items():
        fm_part = fm_part.replace(k, esc(val))
        body_part = body_part.replace(k, val)
    text = fm_part + body_part
    if tdef.get("hub"):
        dest = v.wiki_dir / tdef["folder"] / slug / (slug + ".md")
    elif hub is not None:
        dest = hub.path.parent / tdef.get("subfolder", "") / (slug + ".md")
    else:
        dest = v.wiki_dir / tdef["folder"] / (slug + ".md")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return 0, "created %s" % show(dest), dest


def create_with_companions(ptype, slug, title, **kw):
    """Create a page; for hub types also create their companion pages (work log, ideas)."""
    v = Vault()
    rc, msg, dest = create_page(v, ptype, slug, title, **kw)
    msgs = [msg]
    if rc == 0:
        tdef = v.cfg["types"][ptype]
        hub_slug = dest.stem
        for ctype, suffix in tdef.get("companions", {}).items():
            v = Vault()
            label = {"worklog": "work log", "ideas": "ideas"}.get(ctype, ctype)
            crc, cmsg, _d = create_page(v, ctype, hub_slug + suffix, "%s — %s" % (title.strip(), label),
                                        summary="%s for %s." % (label.capitalize(), title.strip()),
                                        parent=hub_slug)
            msgs.append(cmsg)
        reindex_quietly()
    return rc, msgs, dest


def cmd_new(args):
    rc, msgs, _dest = create_with_companions(
        args.type, args.slug, args.title, summary=args.summary, kind=args.kind, raw=args.raw,
        question=args.question, parent=args.parent, repo=args.repo, due=args.due, severity=args.severity)
    for m in msgs:
        print(m, file=sys.stderr if rc else sys.stdout)
    return rc


def cmd_touch(args):
    v = Vault()
    rc = 0
    for s in args.slugs:
        s = strip_md(s.lower()).split("/")[-1]
        pg = v.by_slug.get(s)
        if not pg:
            print("touch: no wiki page '%s'" % s, file=sys.stderr)
            rc = 1
            continue
        pg.path.write_text(set_fm_field(pg.text, "updated", today()), encoding="utf-8")
        print("touched %s" % pg.rel)
    return rc


def rewrite_links(text, old, new):
    pat = re.compile(r"\[\[(\s*)((?:[^\[\]\|#\n]*/)?)" + re.escape(old) + r"(\.md)?(\s*)(?=[\]\|#\^\\])", re.I)
    return pat.subn(lambda m: "[[" + m.group(1) + m.group(2) + new + (m.group(3) or "") + m.group(4), text)


def cmd_rename(args):
    v = Vault()
    old = strip_md(args.old.lower()).split("/")[-1]
    new = strip_md(args.new.lower())
    pg = v.by_slug.get(old)
    if not pg:
        print("rename: no wiki page '%s'" % old, file=sys.stderr)
        return 2
    if not KEBAB_RE.match(new):
        print("rename: '%s' is not kebab-case" % new, file=sys.stderr)
        return 2
    if new in v.stems and v.stems[new] != [pg.path]:
        print("rename: '%s' already exists" % new, file=sys.stderr)
        return 3
    if new == pg.slug:
        print("rename: nothing to do")
        return 0
    raw_dir = v.raw_dir
    changed = []
    for p in v.md_files:
        try:
            p.relative_to(raw_dir)
            continue  # raw/ is immutable
        except ValueError:
            pass
        text = p.read_text(encoding="utf-8", errors="replace")
        new_text, n = rewrite_links(text, pg.slug, new)
        if n:
            changed.append((p, new_text, n))
    dest = pg.path.with_name(new + ".md")
    if args.dry_run:
        print("rename (dry run): %s -> %s" % (pg.rel, dest.relative_to(v.root).as_posix()))
        for p, _t, n in changed:
            print("  would rewrite %d link(s) in %s" % (n, p.relative_to(v.root).as_posix()))
        return 0
    for p, t, _n in changed:
        p.write_text(t, encoding="utf-8")
    rc, _ = git(v.root, "ls-files", "--error-unmatch", pg.rel)
    if rc == 0:
        rc2, _ = git(v.root, "mv", pg.rel, dest.relative_to(v.root).as_posix())
        if rc2 != 0:
            os.rename(pg.path, dest)
    else:
        os.rename(pg.path, dest)
    print("renamed %s -> %s; rewrote links in %d file(s)"
          % (pg.rel, dest.relative_to(v.root).as_posix(), len(changed)))
    print("next: add the old title to `aliases` if people may search for it; run `wiki.py index`.")
    return 0


def cmd_log(args):
    v = Vault()
    path = v.special("log")
    if args.op not in v.cfg.get("log_ops", []):
        print("log: note — op '%s' is not in config log_ops %s" % (args.op, v.cfg.get("log_ops")), file=sys.stderr)
    if args.date:
        try:
            _dt.date.fromisoformat(args.date)
        except ValueError:
            print("log: --date must be a real YYYY-MM-DD date, got %r" % args.date, file=sys.stderr)
            return 2
    title = " ".join(args.title.split())
    lines = ["## [%s] %s | %s" % (args.date or today(), args.op, title)]

    def links(items):
        return ", ".join("[[%s]]" % strip_md(x).split("/")[-1] for x in items)
    if args.created:
        lines.append("- created: " + links(args.created))
    if args.updated:
        lines.append("- updated: " + links(args.updated))
    for n in args.note or []:
        lines.append("- " + n)
    if not path.exists():
        path.write_text("---\ntype: meta\nsummary: \"Append-only activity log.\"\n---\n# Log\n", encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    text += "\n" + "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    print(lines[0])
    return 0


def _read_defuddle_json(p):
    data = json.loads(Path(p).read_text(encoding="utf-8"))
    md = data.get("contentMarkdown") or data.get("markdown") or ""
    content = data.get("content") or ""
    if not md and content and not content.lstrip().startswith("<"):
        md = content
    meta = {k: data.get(k) for k in ("title", "author", "published", "description", "site", "domain")}
    return md, meta


def cmd_capture(args):
    v = Vault()
    raw = v.raw_dir
    raw.mkdir(parents=True, exist_ok=True)
    meta = {"title": args.title, "author": args.author, "published": args.published, "description": None,
            "site": None, "domain": None}
    content, binary = None, None
    if args.defuddle_json:
        content, m = _read_defuddle_json(args.defuddle_json)
        for k, val in m.items():
            if val and not meta.get(k):
                meta[k] = val
        if not content:
            print("capture: no markdown found in the defuddle JSON. Re-run defuddle with --md -o FILE and use "
                  "--markdown-file FILE instead.", file=sys.stderr)
            return 4
    elif args.markdown_file:
        content = Path(args.markdown_file).read_text(encoding="utf-8", errors="replace")
    elif args.binary:
        binary = Path(args.binary)
        if not binary.exists():
            print("capture: file not found: %s" % binary, file=sys.stderr)
            return 2
    else:
        print("capture: give --defuddle-json, --markdown-file or --binary", file=sys.stderr)
        return 2
    title = (meta.get("title") or "").strip() or (binary.stem if binary else "untitled")
    slug = args.slug or kebab(title, max_words=8, max_len=60)
    ext = binary.suffix.lower() if binary else ".md"
    base = "%s-%s" % (today(), slug)
    dest = raw / (base + ext)
    k = 2
    while dest.exists():
        dest = raw / ("%s-%d%s" % (base, k, ext))
        k += 1
    if binary:
        shutil.copyfile(binary, dest)
    else:
        fm = ["---", "title: %s" % yaml_quote(title)]
        if args.url:
            fm.append("source_url: %s" % yaml_quote(args.url))
        if meta.get("author"):
            fm.append("author: %s" % yaml_quote(meta["author"]))
        if meta.get("published"):
            fm.append("published: %s" % yaml_quote(meta["published"]))
        if meta.get("site") or meta.get("domain"):
            fm.append("site: %s" % yaml_quote(meta.get("site") or meta.get("domain")))
        if meta.get("description"):
            fm.append("description: %s" % yaml_quote(meta["description"]))
        fm.append("captured: %s" % today())
        fm.append("capture_method: %s" % (args.method or ("defuddle" if args.defuddle_json else "manual")))
        fm.append("---")
        body = content
        # if the content already starts with its own frontmatter, keep it as-is below ours
        dest.write_text("\n".join(fm) + "\n\n" + body.lstrip("\ufeff"), encoding="utf-8")
    print(dest.relative_to(v.root).as_posix())
    return 0


# ---------------------------------------------------------------------------
# projects: work log, ideas, issues, context, global hooks
# ---------------------------------------------------------------------------

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
WIKI_CMD = "python3 " + shlex.quote(str(ROOT / "_system" / "wiki.py"))  # shell-safe even with spaces in the path
STATE_FILE = SYSTEM_DIR / ".state" / "sessions.json"
IGNORE_FILE = SYSTEM_DIR / "ignored-repos.txt"


def in_vault(path):
    rp = os.path.realpath(os.path.expanduser(str(path)))
    return rp == str(ROOT) or rp.startswith(str(ROOT) + os.sep)


def repo_root(path):
    rc, out = git(path, "rev-parse", "--show-toplevel")
    return out.strip() if rc == 0 and out.strip() else None


def ignored_repos():
    if not IGNORE_FILE.exists():
        return []
    return [os.path.realpath(os.path.expanduser(l.strip())) for l in IGNORE_FILE.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def is_ignored(path):
    rp = os.path.realpath(os.path.expanduser(str(path)))
    return any(rp == ig or rp.startswith(ig + os.sep) for ig in ignored_repos())


def git_ref(path):
    if not path or not os.path.isdir(path):
        return ""
    rc, br = git(path, "rev-parse", "--abbrev-ref", "HEAD")
    rc2, sha = git(path, "rev-parse", "--short", "HEAD")
    if rc != 0 or rc2 != 0:
        return ""
    return "`%s` @ `%s`" % (br.strip(), sha.strip())


def resolve_project(v, project=None, cwd=None):
    """Return (hub, error). Explicit slug wins; otherwise map cwd to a registered repo."""
    if project:
        hub = v.project_by_slug(project)
        return (hub, None) if hub else (None, "no project page '%s' (see `wiki.py project list`)" % project)
    cwd = cwd or os.getcwd()
    hub = v.find_project(cwd)
    if hub:
        return hub, None
    root = repo_root(cwd) or cwd
    return None, ("%s is not registered to a project. Register it: %s project add <slug> "
                  "--title \"…\" --summary \"…\" --repo \"%s\"   (or pass --project <slug>)" % (root, WIKI_CMD, root))


def insert_in_section(text, heading, line):
    """Insert `line` at the end of the `## heading` section (created at the end if missing)."""
    m = re.search(r"^## %s[ \t]*$" % re.escape(heading), text, re.M)
    if not m:
        return text.rstrip("\n") + "\n\n## %s\n%s\n" % (heading, line)
    nxt = re.search(r"^## ", text[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(text)
    kept = [l for l in text[m.end():end].strip("\n").split("\n")
            if l.strip() and l.strip() not in ("-", "- [ ]")]  # drop empty template bullets
    section = "\n" + "\n".join(kept + [line]) + "\n"
    return text[:m.end()] + section + ("\n" + text[end:] if nxt else "")


def _rel_to_repo(fp, hub):
    for r in hub.list_field("repo"):
        rp = os.path.realpath(os.path.expanduser(str(r)))
        a = os.path.realpath(os.path.expanduser(str(fp)))
        if a.startswith(rp + os.sep):
            return a[len(rp) + 1:]
    return str(fp)


def append_worklog(v, hub, title, did=(), files=(), issues=(), nxt=(), notes=(), session=None, cwd=None):
    wls = v.children(hub, "worklog")
    if not wls:
        suffix = v.tdef("project").get("companions", {}).get("worklog", "-log")
        rc, msg, _d = create_page(v, "worklog", hub.slug + suffix, "%s — work log" % hub.title,
                                  summary="Work log for %s." % hub.title, parent=hub.slug)
        if rc != 0:
            raise RuntimeError(msg)
        v = Vault()
        hub = v.by_slug[hub.slug]
        wls = v.children(hub, "worklog")
    wl = wls[0]
    text = wl.path.read_text(encoding="utf-8")
    bullets = ["- **Did:** %s" % d for d in did if d.strip()]
    rel_files = []
    for f in files or ():
        rf = _rel_to_repo(f, hub)
        if rf not in rel_files:
            rel_files.append(rf)
    if rel_files:
        shown = rel_files[:15]
        bullets.append("- **Files:** " + ", ".join("`%s`" % f for f in shown)
                       + (" … +%d more" % (len(rel_files) - 15) if len(rel_files) > 15 else ""))
    for i in issues or ():
        slug = strip_md(i.lower()).strip("[]")
        if slug not in v.by_slug and (hub.slug + "-" + slug) in v.by_slug:
            slug = hub.slug + "-" + slug
        bullets.append("- **Issue:** " + ("[[%s]]" % slug if slug in v.by_slug else i))
    bullets += ["- **Next:** %s" % n for n in nxt or () if n.strip()]
    bullets += ["- **Note:** %s" % n for n in notes or () if n.strip()]
    repo_dir = None
    if cwd and not in_vault(cwd):
        repo_dir = repo_root(cwd)
    if not repo_dir and hub.list_field("repo"):
        repo_dir = os.path.expanduser(str(hub.list_field("repo")[0]))
    ref = git_ref(repo_dir)
    title = " ".join(title.split()) or "Work session"
    marker = "%%%% session: %s %%%%" % session if session else None
    if marker and marker in text:
        pos = text.index(marker)
        nxt_h = re.search(r"^## ", text[pos:], re.M)
        end = pos + nxt_h.start() if nxt_h else len(text)
        entry = text[pos:end]
        add = ["- **Update:** %s" % title] + bullets
        if ref and ref not in entry:
            add.append("- **Ref:** %s" % ref)
        new_entry = entry.rstrip("\n") + "\n" + "\n".join(add) + "\n"
        text = text[:pos] + new_entry + ("\n" if nxt_h else "") + text[end:]
        how = "updated session entry"
    else:
        lines = ["## %s · %s" % (today(), title)]
        if marker:
            lines.append(marker)
        lines += bullets
        if ref:
            lines.append("- **Ref:** %s" % ref)
        text = text.rstrip("\n") + "\n\n" + "\n".join(lines) + "\n"
        how = "new entry"
    text = set_fm_field(text, "updated", today())
    wl.path.write_text(text, encoding="utf-8")
    reindex_quietly()
    return wl, how


def cmd_worklog(args):
    v = Vault()
    hub, err = resolve_project(v, args.project, args.cwd)
    if not hub:
        print("worklog: " + err, file=sys.stderr)
        return 2
    try:
        wl, how = append_worklog(v, hub, args.title, did=args.did or (), files=args.files or (),
                                 issues=args.issue or (), nxt=args.next or (), notes=args.note or (),
                                 session=args.session, cwd=args.cwd or os.getcwd())
    except RuntimeError as exc:
        print("worklog: %s" % exc, file=sys.stderr)
        return 2
    print("worklog: %s in %s" % (how, show(wl.path)))
    return 0


def cmd_idea(args):
    v = Vault()
    hub, err = resolve_project(v, args.project, args.cwd)
    if not hub:
        print("idea: " + err, file=sys.stderr)
        return 2
    pages = v.children(hub, "ideas")
    if not pages:
        suffix = v.tdef("project").get("companions", {}).get("ideas", "-ideas")
        rc, msg, _d = create_page(v, "ideas", hub.slug + suffix, "%s — ideas" % hub.title,
                                  summary="Ideas for %s." % hub.title, parent=hub.slug)
        if rc != 0:
            print(msg, file=sys.stderr)
            return 2
        v = Vault()
        pages = v.children(v.by_slug[hub.slug], "ideas")
    pg = pages[0]
    line = "- [ ] %s _(%s)_" % (" ".join(args.text.split()), today())
    if args.detail:
        line += "\n    - " + "\n    - ".join(args.detail)
    text = insert_in_section(pg.path.read_text(encoding="utf-8"), "Open", line)
    pg.path.write_text(set_fm_field(text, "updated", today()), encoding="utf-8")
    reindex_quietly()
    print("idea: added to %s" % show(pg.path))
    return 0


def cmd_issue(args):
    v = Vault()
    hub, err = resolve_project(v, args.project, args.cwd)
    if not hub:
        print("issue: " + err, file=sys.stderr)
        return 2
    slug = args.slug or kebab(args.title, max_words=6, max_len=50)
    rc, msg, dest = create_page(v, "issue", slug, args.title, summary=args.summary, parent=hub.slug,
                                severity=args.severity)
    print(msg, file=sys.stderr if rc else sys.stdout)
    if rc == 0:
        if args.status and args.status != "open":
            dest.write_text(set_fm_field(dest.read_text(encoding="utf-8"), "status", args.status), encoding="utf-8")
        reindex_quietly()
        print("next: fill Symptom / Cause / Fix in %s; link it from the work log with --issue %s" % (show(dest), dest.stem))
    return rc


def cmd_project(args):
    v = Vault()
    if args.action == "list":
        hubs = sorted(v.hubs("project"), key=lambda h: h.slug)
        if not hubs:
            print("project: none yet — `wiki.py project add <slug> --title … --summary … --repo <path>`")
        for h in hubs:
            n_open = sum(1 for i in v.children(h, "issue") if i.field("status") == "open")
            print("%-24s %-9s %d open issue(s)  last log %-10s  %s"
                  % (h.slug, h.field("status"), n_open, last_activity(v, h) or "-", ", ".join(map(str, h.list_field("repo")))))
        return 0
    if args.action == "which":
        hub = v.find_project(args.path or os.getcwd())
        if not hub:
            print("project: none for %s" % (args.path or os.getcwd()))
            return 1
        print(hub.slug)
        return 0
    if args.action == "ignore":
        path = os.path.realpath(os.path.expanduser(args.path or args.slug or repo_root(os.getcwd()) or os.getcwd()))
        existing = IGNORE_FILE.read_text(encoding="utf-8") if IGNORE_FILE.exists() else \
            "# Repos the global wiki hooks should never track (one absolute path per line).\n"
        if path not in ignored_repos():
            IGNORE_FILE.write_text(existing.rstrip("\n") + "\n" + path + "\n", encoding="utf-8")
        print("project: ignoring %s" % path)
        return 0
    # add
    if not args.slug or not args.title:
        print("project add: give SLUG and --title", file=sys.stderr)
        return 2
    repo = args.path or args.repo
    if not repo:
        cwd = os.getcwd()
        repo = None if in_vault(cwd) else (repo_root(cwd) or cwd)
    repo = os.path.realpath(os.path.expanduser(repo)) if repo else ""
    if repo:
        other = v.find_project(repo)
        if other is not None and os.path.realpath(os.path.expanduser(str(other.list_field("repo")[0]))) == repo:
            print("project add: %s is already registered as [[%s]]" % (repo, other.slug), file=sys.stderr)
            return 3
    rc, msgs, dest = create_with_companions("project", args.slug, args.title, summary=args.summary, repo=repo)
    for m in msgs:
        print(m, file=sys.stderr if rc else sys.stdout)
    if rc == 0 and args.stack:
        dest.write_text(set_fm_field(dest.read_text(encoding="utf-8"), "stack",
                                     "[" + ", ".join(yaml_quote(x) for x in args.stack) + "]"), encoding="utf-8")
    if rc == 0:
        print("next: fill the hub's 'What it is' section; run /wiki-explain in the repo for code explainers")
    return rc


def _entries(text, n):
    parts = re.split(r"(?m)^(?=## \d{4}-\d{2}-\d{2})", text)
    ents = [p.strip() for p in parts if re.match(r"## \d{4}-\d{2}-\d{2}", p)]
    out = []
    for e in ents[-n:]:
        lines = [l for l in e.splitlines() if not SESSION_RE.match(l) and l.strip()]
        keep = lines[:1] + [l for l in lines[1:] if not l.startswith("- **Ref:**")][:5]
        out.append("\n".join(keep))
    return out


def hub_unfilled(hub):
    """True while the project hub's 'What it is' still has the template's empty bullets."""
    return bool(re.search(r"^- \*\*Problem:\*\*\s*$", hub.body, re.M))


def project_context(v, hub, session=None):
    cfg = v.cfg
    wiki_py = WIKI_CMD
    L = ["<project-wiki-context>",
         "Personal wiki project: %s ([[%s]]) — %s · status %s" % (hub.title, hub.slug, hub.field("summary"), hub.field("status")),
         "Hub page: %s" % hub.path]
    issues = [i for i in v.children(hub, "issue") if i.field("status") in ("open", "workaround")]
    if issues:
        L.append("Open issues (%d):" % len(issues))
        for i in sorted(issues, key=lambda p: p.slug)[:8]:
            L.append("  - %s [%s, sev %s] — %s" % (i.slug, i.field("status"), i.field("severity"), i.field("summary")))
    docs = v.children(hub, "doc")
    if docs:
        L.append("Explainers: " + ", ".join("%s (%s)" % (d.slug, d.field("kind")) for d in sorted(docs, key=lambda p: p.slug)[:10]))
    if graphify_ready(cfg):
        for r in hub.list_field("repo"):
            g = Path(os.path.expanduser(str(r))) / "graphify-out" / "graph.json"
            if g.is_file():
                L.append("Code graph (graphify, built %s): %s. For structure questions (what calls X, how A reaches B) try "
                         "`graphify query \"…\"` / `graphify path A B` before reading files; cite the code, not the graph. "
                         "Refresh after big changes: `graphify update .` (code only, no LLM)."
                         % (_dt.date.fromtimestamp(g.stat().st_mtime).isoformat(), g))
                break
    for wl in v.children(hub, "worklog"):
        ents = _entries(wl.body, cfg.get("context_log_entries", 3))
        if ents:
            L.append("Recent work (%s):" % wl.slug)
            L += ["  " + l for e in ents for l in e.splitlines()]
    ideas = v.children(hub, "ideas")
    if ideas:
        n = len(re.findall(r"^- \[ \]", ideas[0].body, re.M))
        L.append("Ideas: %d open in %s" % (n, ideas[0].slug))
    if hub_unfilled(hub):
        L.append("The hub's 'What it is' / 'How to explain it' sections are still empty: fill them (3–6 plain lines "
                 "from README + code) when you get a chance.")
    L += ["Keep this project's wiki current (skill: wiki-log)%s:" % (" — session id %s" % session if session else ""),
          "  - after meaningful work: %s worklog \"<what, ≤80 chars>\"%s --did \"…\" --files a b [--issue <slug>] [--next \"…\"]"
          % (wiki_py, " --session %s" % session if session else ""),
          "  - non-trivial bug/obstacle: %s issue \"<title>\" --summary \"…\" --severity low|medium|high; when solved set status + Cause/Fix"
          % wiki_py,
          "  - before debugging an error, check open/fixed issues above and `%s search \"<error text>\"`" % wiki_py,
          "  - ideas only when the user voices one: %s idea \"…\"" % wiki_py,
          "</project-wiki-context>"]
    return "\n".join(L)


def cmd_context(args):
    v = Vault()
    cwd = args.cwd or os.getcwd()
    hub = v.project_by_slug(args.project) if args.project else v.find_project(cwd)
    if not hub:
        print("context: no project for %s" % cwd)
        return 1
    print(project_context(v, hub, args.session))
    return 0


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if len(state) > 200:  # keep the most recent sessions only
            state = dict(sorted(state.items(), key=lambda kv: kv[1].get("at", ""))[-200:])
        STATE_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    except OSError:
        pass


def transcript_edits(transcript_path, start=0):
    """(files edited outside the vault since the last `wiki.py worklog` call and after transcript line
    `start`, number of transcript lines read)."""
    edits, n = [], 0
    if not transcript_path or not os.path.exists(os.path.expanduser(transcript_path)):
        return edits, n
    with open(os.path.expanduser(transcript_path), encoding="utf-8", errors="replace") as fh:
        for line in fh:
            n += 1
            if n <= start:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            msg = obj.get("message") if isinstance(obj, dict) else None
            content = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                name, inp = c.get("name"), c.get("input") or {}
                if name == "Bash" and re.search(r"wiki\.py[\"']?\s+worklog\b", str(inp.get("command", ""))):
                    edits = []
                elif name in EDIT_TOOLS:
                    fp = inp.get("file_path") or inp.get("notebook_path")
                    if fp and not in_vault(fp):
                        edits.append(fp)
    return edits, n


def git_busy(root):
    """True while a merge, rebase, cherry-pick or revert is in progress, or paths are unmerged."""
    gd = Path(root) / ".git"
    if any((gd / n).exists() for n in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD")):
        return True
    rc, out = git(root, "diff", "--name-only", "--diff-filter=U")
    return rc == 0 and bool(out.strip())


def vault_commit(msg):
    if not (ROOT / ".git").exists() or os.environ.get("WIKI_AUTOSAVE", "1") == "0" or git_busy(ROOT):
        return False
    rc, out = git(ROOT, "status", "--porcelain")
    if rc != 0 or not out.strip():
        return False
    git(ROOT, "add", "-A")
    rc, _ = git(ROOT, "commit", "-q", "-m", msg)
    return rc == 0


def cmd_commit(args):
    ok = vault_commit(args.message if args.message.startswith("wiki:") else "wiki: " + args.message)
    print("commit: %s" % ("done" if ok else "nothing to commit"))
    return 0


def cmd_hook(args):
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    cwd = data.get("cwd") or os.getcwd()
    if in_vault(cwd) or is_ignored(cwd):
        return 0  # the vault has its own project-level hooks
    v = Vault()
    hub = v.find_project(cwd)
    sid = data.get("session_id")
    wiki_py = WIKI_CMD
    if args.event == "session-start":
        if hub:
            print(project_context(v, hub, sid))
        elif repo_root(cwd):
            print("<project-wiki-context>Personal wiki: this repo (%s) is not tracked yet. Once you do meaningful work "
                  "here, register it with `%s project add <slug> --title \"…\" --summary \"…\" --repo \"%s\"` and log "
                  "the work (skill: wiki-log). If the user doesn't want it tracked: `%s project ignore %s`."
                  "</project-wiki-context>" % (repo_root(cwd), wiki_py, repo_root(cwd), wiki_py, repo_root(cwd)))
        return 0
    state = load_state()
    st = state.get(sid or "", {})
    if args.event == "stop":
        if os.environ.get("WIKI_REMIND", "1") == "0" or data.get("stop_hook_active"):
            return 0
        # count only edits after the last worklog call, the last auto-log and the last reminder (one nudge per batch)
        edits, n = transcript_edits(data.get("transcript_path"), max(st.get("logged", 0), st.get("reminded", 0)))
        if len(edits) < v.cfg.get("remind_min_edits", 3):
            return 0
        if not hub and not repo_root(cwd):
            return 0
        files = sorted({(_rel_to_repo(f, hub) if hub else f) for f in edits})
        if hub:
            reason = ("Personal wiki: %d edit(s) in project '%s' since the last work-log entry (%s). Before you finish, "
                      "record what was done in ONE short call — the outcome and why, not a diff:\n"
                      "%s worklog \"<what, ≤80 chars>\" --session %s --did \"…\" --files <paths> [--issue <slug>] [--next \"…\"]\n"
                      "If you hit a non-trivial bug, also create or update an issue page (`%s issue …`).%s Then finish "
                      "your reply as you would have."
                      % (len(edits), hub.slug, ", ".join(files[:8]), wiki_py, sid, wiki_py,
                         (" Also fill the empty 'What it is' and 'How to explain it' sections of the hub page %s "
                          "(plain language, from README + code; delete the template comments)." % hub.path)
                         if hub_unfilled(hub) else ""))
        else:
            root = repo_root(cwd)
            reason = ("Personal wiki: this repo (%s) has edits but isn't registered. Register it once — "
                      "`%s project add <slug> --title \"…\" --summary \"<what the project is>\" --repo \"%s\"`, fill the hub page's "
                      "'What it is' and 'How to explain it' sections from README + code, then log "
                      "the work: `%s worklog \"…\" --session %s --did \"…\" --files …`. If this repo shouldn't be "
                      "tracked, run `%s project ignore %s` instead. Then finish your reply as you would have."
                      % (root, wiki_py, root, wiki_py, sid, wiki_py, root))
        if sid:
            state[sid] = dict(st, reminded=n, at=_dt.datetime.now().isoformat())
            save_state(state)
        print(json.dumps({"decision": "block", "reason": reason}))
        return 0
    if args.event == "session-end":
        edits, n = transcript_edits(data.get("transcript_path"), st.get("logged", 0))
        if hub and edits:
            append_worklog(v, hub, "Auto-logged: session ended without a summary", files=edits,
                           notes=["unsummarized — files touched after the last work-log entry"], session=sid, cwd=cwd)
        if sid:  # a resumed session must not auto-log the same edits again
            state[sid] = dict(st, logged=n, at=_dt.datetime.now().isoformat())
            save_state(state)
        vault_commit("wiki: autosave | %s session" % (hub.slug if hub else os.path.basename(cwd)))
        return 0
    return 0


# ---------------------------------------------------------------------------
# install-global: user-level hooks, skills and CLAUDE.md block
# ---------------------------------------------------------------------------

GLOBAL_MARK = "agent-wiki-kit"


def _is_our_hook(command):
    """Matches hooks written by any install of this kit, whatever the OS path separator."""
    c = str(command).replace("\\", "/")
    return "_system/wiki.py" in c and re.search(r"\bhook (session-start|stop|session-end)\b", c) is not None


def cmd_install_global(args):
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    src = SYSTEM_DIR / "global"
    wiki_py = str(ROOT / "_system" / "wiki.py")
    actions = []

    def render(text):
        return text.replace("{{VAULT}}", str(ROOT)).replace("{{WIKI_PY}}", WIKI_CMD)

    # settings.json
    sp = home / "settings.json"
    settings = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    before = json.dumps(settings, sort_keys=True)
    hooks = settings.setdefault("hooks", {})
    for event, sub in (("SessionStart", "session-start"), ("Stop", "stop"), ("SessionEnd", "session-end")):
        groups = [g for g in hooks.get(event, [])
                  if not any(_is_our_hook(h.get("command", "")) for h in g.get("hooks", []))]
        if not args.uninstall:
            groups.append({"hooks": [{"type": "command", "command": 'python3 "%s" hook %s' % (wiki_py, sub),
                                      "timeout": 30}]})
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)
    perms = settings.setdefault("permissions", {})
    allow_rule = "Bash(%s *)" % WIKI_CMD
    allow = [a for a in perms.get("allow", []) if not (a.startswith("Bash(python3 ")
                                                       and "_system/wiki.py" in str(a).replace("\\", "/"))]
    dirs = [d for d in perms.get("additionalDirectories", []) if d != str(ROOT)]
    if not args.uninstall:
        allow.append(allow_rule)
        dirs.append(str(ROOT))
    for key, val in (("allow", allow), ("additionalDirectories", dirs)):
        if val:
            perms[key] = val
        else:
            perms.pop(key, None)
    if not perms:
        settings.pop("permissions", None)
    if json.dumps(settings, sort_keys=True) != before:
        actions.append(("settings", sp, json.dumps(settings, indent=2, ensure_ascii=False) + "\n"))

    # CLAUDE.md block
    cp = home / "CLAUDE.md"
    cur = cp.read_text(encoding="utf-8") if cp.exists() else ""
    start, end = "<!-- %s:start -->" % GLOBAL_MARK, "<!-- %s:end -->" % GLOBAL_MARK
    region = current_region(cur, start, end)
    block = "" if args.uninstall else "%s\n%s\n%s" % (start, render((src / "CLAUDE-block.md").read_text(encoding="utf-8")).strip(), end)
    if region is not None:
        new = cur.replace(region, block)
    else:
        new = cur if args.uninstall else (cur.rstrip("\n") + ("\n\n" if cur.strip() else "") + block + "\n")
    new = re.sub(r"\n{3,}", "\n\n", new)
    if new != cur:
        actions.append(("CLAUDE.md", cp, new))

    # skills
    for sdir in sorted((src / "skills").iterdir()) if (src / "skills").exists() else []:
        dest = home / "skills" / sdir.name / "SKILL.md"
        if args.uninstall:
            if dest.exists() and GLOBAL_MARK in dest.read_text(encoding="utf-8"):
                actions.append(("remove-skill", dest, None))
            continue
        body = render((sdir / "SKILL.md").read_text(encoding="utf-8"))
        if dest.exists() and GLOBAL_MARK not in dest.read_text(encoding="utf-8"):
            print("install-global: skipping %s — a skill with that name exists and isn't ours" % dest, file=sys.stderr)
            continue
        if not dest.exists() or dest.read_text(encoding="utf-8") != body:
            actions.append(("skill", dest, body))

    if not actions:
        print("install-global: already up to date (%s)" % home)
        return 0
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    for kind, path, content in actions:
        print("%s %s %s" % ("would" if args.dry_run else "→", kind, path))
        if args.dry_run:
            continue
        if path.exists() and kind in ("settings", "CLAUDE.md"):
            shutil.copyfile(path, str(path) + ".wiki-backup-" + stamp)
        if kind == "remove-skill":
            shutil.rmtree(path.parent, ignore_errors=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if not args.dry_run:
        print("install-global: %s. Backups: *.wiki-backup-%s. Restart Claude Code sessions to pick up hooks."
              % ("removed" if args.uninstall else "installed", stamp))
    return 0


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Optional integrations (off unless the human turns them on)
# ---------------------------------------------------------------------------

def graphify_enabled(cfg):
    return bool((cfg.get("integrations") or {}).get("graphify"))


def graphify_ready(cfg):
    """Enabled in config AND the graphify CLI is on PATH. Skills gate every graphify step on this."""
    return graphify_enabled(cfg) and bool(shutil.which("graphify"))


def set_integration(name, on, root=None):
    cfg_path = Path(root or ROOT) / "_system" / "wiki.config.json"
    text = cfg_path.read_text(encoding="utf-8")
    val = "true" if on else "false"
    new, n = re.subn(r'("%s"\s*:\s*)(true|false)' % re.escape(name), r"\g<1>" + val, text, count=1)
    if not n:  # older config without the key: rewrite it (loses hand formatting, keeps content)
        data = json.loads(text)
        data.setdefault("integrations", {})[name] = on
        new = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    cfg_path.write_text(new, encoding="utf-8")


def graph_gaps(v, graph_path):
    """From a graphify graph built over wiki/: page pairs the graph connects that don't link each other,
    and clusters spread over ≥3 pages with no concept/synthesis page among them. Hints for lint, not facts."""
    g = json.loads(Path(graph_path).read_text(encoding="utf-8"))
    skip = set(v.cfg.get("special_pages", []))
    node_page, node_label = {}, {}
    for nd in g.get("nodes", []):
        pg = v.by_slug.get(Path(str(nd.get("source_file") or "")).stem.lower())
        if pg is not None and pg.slug not in skip:
            node_page[nd["id"]] = pg
            node_label[nd["id"]] = nd.get("label") or nd["id"]
    links = {pg.slug.lower(): {t.split("/")[-1].lower() for t, _ in pg.body_links + pg.prop_links} for pg in v.pages}
    pairs = {}
    for e in g.get("links", g.get("edges", [])):
        a, b = node_page.get(e.get("source")), node_page.get(e.get("target"))
        if a is None or b is None or a is b:
            continue
        sa, sb = sorted((a.slug.lower(), b.slug.lower()))
        if sb in links.get(sa, ()) or sa in links.get(sb, ()):
            continue
        p = pairs.setdefault((sa, sb), {"n": 0, "rel": Counter(), "ex": None})
        p["n"] += 1
        p["rel"][e.get("relation", "?")] += 1
        p["ex"] = p["ex"] or (node_label[e["source"]], node_label[e["target"]])
    clusters = defaultdict(set)
    names = {}
    for nd in g.get("nodes", []):
        if nd.get("id") in node_page and nd.get("community") is not None:
            clusters[nd["community"]].add(node_page[nd["id"]])
            names.setdefault(nd["community"], nd.get("community_name") or "community %s" % nd["community"])
    orphan_clusters = [(names[c], sorted(p.slug for p in pgs)) for c, pgs in clusters.items()
                       if len(pgs) >= 3 and not any(p.type in ("concept", "synthesis") for p in pgs)]
    return sorted(pairs.items(), key=lambda kv: -kv[1]["n"]), sorted(orphan_clusters, key=lambda c: -len(c[1]))


def cmd_graphify(args):
    if args.action == "gaps":
        v = Vault()
        gp = Path(args.graph) if args.graph else v.root / "graphify-out" / "graph.json"
        if not gp.is_file():
            print("graphify gaps: no graph at %s (build one over wiki/ first)" % gp)
            return 2
        pairs, clusters = graph_gaps(v, gp)
        print("Unlinked page pairs the graph connects (%d) — verify by reading both before linking:" % len(pairs))
        for (a, b), p in pairs[:args.n]:
            print("  %s <-> %s · %d edge(s): %s · e.g. \"%s\" — \"%s\"" % (
                a, b, p["n"], ", ".join(r for r, _ in p["rel"].most_common(2)), p["ex"][0], p["ex"][1]))
        print("Clusters over ≥3 pages without a concept/synthesis page (%d) — candidate concept pages:" % len(clusters))
        for name, slugs in clusters[:args.n]:
            print("  \"%s\": %s" % (name, ", ".join(slugs)))
        return 0
    if args.action in ("on", "off"):
        set_integration("graphify", args.action == "on")
    cfg = load_config()
    cli = shutil.which("graphify")
    print("graphify: %s · cli: %s" % ("enabled" if graphify_enabled(cfg) else "disabled",
                                      cli or "not found (install: uv tool install graphifyy)"))
    if args.action == "on" and not cli:
        print("note: enabled, but skills skip graphify until the CLI is installed")
    return 0 if graphify_ready(cfg) else 1


def cmd_selftest(args):
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    real_root = ROOT
    tmp = Path(tempfile.mkdtemp(prefix="wiki-selftest-"))
    try:
        shutil.copytree(SYSTEM_DIR, tmp / "_system",
                        ignore=shutil.ignore_patterns("reports", "__pycache__"))
        for d in ("raw/assets", "wiki/sources", "wiki/projects", "wiki/learning", "wiki/concepts", "wiki/syntheses"):
            (tmp / d).mkdir(parents=True, exist_ok=True)
        for name in ("hot", "overview", "questions"):
            (tmp / "wiki" / (name + ".md")).write_text(
                "---\ntype: meta\nsummary: \"%s page\"\n---\n# %s\n" % (name, name.title()), encoding="utf-8")
        (tmp / "wiki" / "log.md").write_text("---\ntype: meta\nsummary: \"log\"\n---\n# Log\n", encoding="utf-8")
        (tmp / "wiki" / "index.md").write_text("---\ntype: meta\nsummary: \"index\"\n---\n# Index\n", encoding="utf-8")
        (tmp / "raw" / "2026-01-01-paper.md").write_text("# A paper\nTransformers use attention.\n", encoding="utf-8")
        script = tmp / "_system" / "wiki.py"
        env = dict(os.environ, WIKI_ROOT=str(tmp))

        def run(*a, stdin=None):
            r = subprocess.run([sys.executable, str(script)] + list(a), capture_output=True, text=True,
                               env=env, input=stdin)
            return r.returncode, r.stdout + r.stderr

        rc, out = run("pending")
        check("pending detects un-ingested raw file", "2026-01-01-paper.md" in out, out)
        rc, out = run("new", "source", "paper", "--title", "A Paper", "--raw", "raw/2026-01-01-paper.md",
                      "--kind", "paper", "--summary", 'Says "attention" matters.')
        check("new source page (auto src- prefix)", rc == 0 and (tmp / "wiki/sources/src-paper.md").exists(), out)
        rc, out = run("pending")
        check("pending clears after source page exists", "none" in out, out)
        rc, out = run("new", "concept", "attention", "--title", "Attention", "--summary", "Weighting inputs.")
        check("new concept page", rc == 0, out)
        rc, out = run("new", "concept", "attention", "--title", "Attention")
        check("new refuses duplicates", rc == 3, out)
        rc, out = run("new", "concept", "Bad Slug", "--title", "x")
        check("new rejects non-kebab slugs", rc == 2, out)
        cpath = tmp / "wiki/concepts/attention.md"
        c = cpath.read_text(encoding="utf-8")
        c = set_fm_field(c, "sources", '["[[src-paper]]"]')
        c += "\nAttention weights inputs ([[src-paper]]).\n"
        cpath.write_text(c, encoding="utf-8")
        spath = tmp / "wiki/sources/src-paper.md"
        spath.write_text(spath.read_text(encoding="utf-8") + "\nDiscusses [[attention]].\n", encoding="utf-8")
        for p in (cpath, spath):  # an agent fills placeholders and deletes guidance comments
            t = re.sub(r"\{\{[^}]+\}\}", "x", p.read_text(encoding="utf-8"))
            p.write_text(COMMENT_RE.sub("", t), encoding="utf-8")
        rc, out = run("index")
        check("index builds", rc == 0, out)
        rc, out = run("index", "--check")
        check("index --check passes when fresh", rc == 0, out)
        rc, out = run("lint")
        check("lint clean on a valid mini wiki", rc == 0, out)
        cpath.write_text(cpath.read_text(encoding="utf-8") + "\nSee [[does-not-exist]].\n", encoding="utf-8")
        rc, out = run("lint")
        check("lint catches broken link (exit 1)", rc == 1 and "broken-link" in out, out)
        cpath.write_text(cpath.read_text(encoding="utf-8").replace("\nSee [[does-not-exist]].\n", ""), encoding="utf-8")
        rc, out = run("rename", "attention", "attention-mechanism")
        moved = tmp / "wiki/concepts/attention-mechanism.md"
        check("rename moves file", rc == 0 and moved.exists(), out)
        check("rename rewrites links",
              "[[attention-mechanism]]" in spath.read_text(encoding="utf-8"), spath.read_text(encoding="utf-8"))
        rc, out = run("index")
        rc, out = run("lint")
        check("lint clean after rename + index", rc == 0, out)
        (tmp / "raw" / "2026-01-01-paper.md").write_text("tampered\n", encoding="utf-8")
        rc, out = run("lint")
        check("lint detects changed raw file", "raw-changed" in out, out)
        rc, out = run("log", "ingest", "A Paper", "--created", "src-paper", "--note", "test")
        logt = (tmp / "wiki/log.md").read_text(encoding="utf-8")
        check("log appends parseable entry",
              re.search(r"^## \[\d{4}-\d{2}-\d{2}\] ingest \| A Paper$", logt, re.M) and "[[src-paper]]" in logt, logt)
        rc, out = run("search", "attention")
        check("search finds the concept", "attention-mechanism" in out, out)
        rc, out = run("status", "--hook")
        check("status --hook renders", "<wiki-session-context>" in out and "Pages:" in out, out)
        # --- optional graphify integration: off by default, output dirs never become pages ---
        rc, out = run("graphify")
        check("graphify is disabled by default (exit 1)", rc == 1 and "disabled" in out, out)
        fakebin = tmp / "_fakebin"
        fakebin.mkdir()
        (fakebin / "graphify").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (fakebin / "graphify").chmod(0o755)
        env_saved = env.copy()
        env["PATH"] = str(fakebin) + os.pathsep + env.get("PATH", "")
        rc, out = run("graphify")
        check("graphify stays off even when installed", rc == 1 and "disabled" in out, out)
        rc, out = run("graphify", "on")
        check("graphify on + installed → ready (exit 0)", rc == 0 and "enabled" in out, out)
        env.clear(); env.update(env_saved)
        rc, out = run("graphify")
        check("graphify enabled but CLI missing → not ready", rc == 1 or shutil.which("graphify"), out)
        rc, out = run("graphify", "off")
        check("graphify off persists in config",
              rc == 1 and '"graphify": false' in (tmp / "_system/wiki.config.json").read_text(encoding="utf-8"), out)
        (tmp / "wiki/concepts/graphify-out").mkdir()
        (tmp / "wiki/concepts/graphify-out/GRAPH_REPORT.md").write_text("# Graph report\n[[nowhere]]\n", encoding="utf-8")
        (tmp / "raw/graphify-out").mkdir()
        (tmp / "raw/graphify-out/converted.md").write_text("x\n", encoding="utf-8")
        rc, out = run("pending")
        check("graphify-out in raw/ is not a pending source", "graphify-out" not in out, out)
        rc, out = run("lint")
        check("graphify-out in wiki/ is not linted as pages", "GRAPH_REPORT" not in out and "nowhere" not in out, out)
        shutil.rmtree(tmp / "wiki/concepts/graphify-out"); shutil.rmtree(tmp / "raw/graphify-out")
        # --- projects: hub + companions, worklog, idea, issue, hooks ---
        outside = Path(tempfile.mkdtemp(prefix="wiki-selftest-repo-"))
        repo = outside / "demo"
        (repo / "src").mkdir(parents=True)
        rc, out = run("project", "add", "demo", "--title", "Demo App", "--summary", "A demo.", "--repo", str(repo))
        hubp = tmp / "wiki/projects/demo/demo.md"
        check("project add creates hub + log + ideas",
              rc == 0 and hubp.exists() and (tmp / "wiki/projects/demo/demo-log.md").exists()
              and (tmp / "wiki/projects/demo/demo-ideas.md").exists(), out)
        rc, out = run("project", "which", "--path", str(repo / "src"))
        check("project which maps a subdirectory to its project", rc == 0 and out.strip() == "demo", out)
        rc, out = run("issue", "Login crashes", "--summary", "Crash on empty password.", "--cwd", str(repo), "--severity", "high")
        check("issue created in issues/ with project prefix",
              rc == 0 and (tmp / "wiki/projects/demo/issues/demo-login-crashes.md").exists(), out)
        rc, out = run("worklog", "Fixed login", "--cwd", str(repo), "--session", "s1", "--did", "Guarded empty password",
                      "--files", str(repo / "src/a.py"), "--issue", "login-crashes")
        rc2, out2 = run("worklog", "Added test", "--cwd", str(repo), "--session", "s1", "--did", "Regression test")
        logt = (tmp / "wiki/projects/demo/demo-log.md").read_text(encoding="utf-8")
        check("worklog appends one entry per session (merged)",
              rc == 0 and rc2 == 0 and logt.count("%% session: s1 %%") == 1 and "**Update:** Added test" in logt
              and "`src/a.py`" in logt and "[[demo-login-crashes]]" in logt, out + out2 + logt)
        rc, out = run("idea", "Dark mode", "--project", "demo")
        ideat = (tmp / "wiki/projects/demo/demo-ideas.md").read_text(encoding="utf-8")
        check("idea lands under ## Open", rc == 0 and re.search(r"## Open\n- \[ \] Dark mode", ideat), ideat)
        rc, out = run("worklog", "x", "--cwd", str(outside))
        check("worklog refuses unregistered dirs", rc == 2 and "not registered" in out, out)
        hubt = hubp.read_text(encoding="utf-8")
        check("hub section lists issues, log and ideas",
              "[[demo-login-crashes|" in hubt and "[[demo-log|" in hubt and "[[demo-ideas|" in hubt, hubt)
        # an agent fills the new pages
        for p in (tmp / "wiki/projects").rglob("*.md"):
            t = p.read_text(encoding="utf-8")
            body = t.replace(HUB_START, "@@S@@").replace(HUB_END, "@@E@@")
            p.write_text(re.sub(r"<!--.*?-->", "", body, flags=re.S).replace("@@S@@", HUB_START).replace("@@E@@", HUB_END), encoding="utf-8")
        run("index")
        rc, out = run("lint")
        check("lint clean with a project", rc == 0, out)
        rc, out = run("new", "area", "algorithms", "--title", "Algorithms", "--kind", "course", "--summary", "Uni course.")
        rc2, out2 = run("new", "assignment", "hw1", "--parent", "algorithms", "--title", "HW 1", "--kind", "assignment",
                        "--due", "2000-01-01", "--summary", "Sorting.")
        check("area + assignment (prefixed, in assignments/)",
              rc == 0 and rc2 == 0 and (tmp / "wiki/learning/algorithms/assignments/algorithms-hw1.md").exists(), out + out2)
        rc, out = run("lint")
        check("lint flags overdue assignment", "overdue" in out, out)
        rc, out = run("new", "note", "x", "--title", "x", "--kind", "lecture")
        check("child pages require --parent", rc == 2, out)
        rc, out = run("context", "--cwd", str(repo), "--session", "s9")
        check("context shows open issue + recent work",
              rc == 0 and "demo-login-crashes" in out and "Fixed login" in out and "--session s9" in out, out)
        (repo / "graphify-out").mkdir()
        (repo / "graphify-out/graph.json").write_text("{}", encoding="utf-8")
        rc, out = run("context", "--cwd", str(repo))
        check("context hides the code graph while graphify is off", "Code graph" not in out, out)
        env_saved = env.copy()
        env["PATH"] = str(fakebin) + os.pathsep + env.get("PATH", "")
        run("graphify", "on")
        rc, out = run("context", "--cwd", str(repo))
        check("context points at the repo's code graph when graphify is on", "Code graph" in out and "graph.json" in out, out)
        nd = lambda i, f, c: {"id": i, "label": i.upper(), "source_file": f, "community": c, "community_name": "C%d" % c}
        (tmp / "graphify-out").mkdir()
        (tmp / "graphify-out/graph.json").write_text(json.dumps({"nodes": [
            nd("crash", "wiki/projects/demo/issues/demo-login-crashes.md", 0), nd("hub", "wiki/projects/demo/demo.md", 0),
            nd("log", "wiki/projects/demo/demo-log.md", 0), nd("att", "wiki/concepts/attention-mechanism.md", 1),
            nd("paper", "wiki/sources/src-paper.md", 1), nd("idx", "wiki/index.md", 1)],
            "links": [{"source": "crash", "target": "att", "relation": "conceptually_related_to"},
                      {"source": "att", "target": "paper", "relation": "cites"},
                      {"source": "idx", "target": "crash", "relation": "references"}]}), encoding="utf-8")
        rc, out = run("graphify", "gaps")
        check("graphify gaps lists unlinked pairs only",
              rc == 0 and "attention-mechanism <-> demo-login-crashes" in out and "src-paper <->" not in out
              and "index" not in out, out)
        check("graphify gaps flags clusters without a concept page", '"C0"' in out and '"C1"' not in out, out)
        run("graphify", "off")
        env.clear(); env.update(env_saved)
        tr = tmp / "transcript.jsonl"
        tu = lambda name, inp: json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": name, "input": inp}]}})
        tr.write_text("\n".join([tu("Edit", {"file_path": str(repo / "src/a.py")})] * 3) + "\n", encoding="utf-8")
        hin = lambda **kw: json.dumps(dict({"cwd": str(repo), "session_id": "s2", "transcript_path": str(tr)}, **kw))
        rc, out = run("hook", "stop", stdin=hin())
        check("stop hook asks for a work-log entry after edits", rc == 0 and '"decision": "block"' in out, out)
        check("stop hook nudges to fill an empty hub", "What it is" in out, out)
        rc, out = run("hook", "stop", stdin=hin(stop_hook_active=True))
        check("stop hook never loops", rc == 0 and out.strip() == "", out)
        with open(tr, "a", encoding="utf-8") as fh:
            fh.write(tu("Bash", {"command": "python3 %s worklog \"y\"" % script}) + "\n")
        rc, out = run("hook", "stop", stdin=hin())
        check("stop hook quiet once work is logged", out.strip() == "", out)
        with open(tr, "a", encoding="utf-8") as fh:
            fh.write(tu("Write", {"file_path": str(repo / "src/b.py")}) + "\n")
        rc, out = run("hook", "session-end", stdin=hin())
        logt = (tmp / "wiki/projects/demo/demo-log.md").read_text(encoding="utf-8")
        check("session-end auto-logs unlogged edits", "%% session: s2 %%" in logt and "`src/b.py`" in logt, logt)
        rc, out = run("hook", "session-end", stdin=hin())
        logt2 = (tmp / "wiki/projects/demo/demo-log.md").read_text(encoding="utf-8")
        check("resumed session doesn't auto-log the same edits twice", logt2.count("Auto-logged") == 1, logt2)
        env_saved = dict(env)
        env["WIKI_REMIND"] = "0"
        with open(tr, "a", encoding="utf-8") as fh:
            fh.write(tu("Write", {"file_path": str(repo / "src/c.py")}) + "\n")
        rc, out = run("hook", "session-end", stdin=hin())
        env.clear(); env.update(env_saved)
        check("WIKI_REMIND=0 keeps the session-end auto-log", "`src/c.py`" in
              (tmp / "wiki/projects/demo/demo-log.md").read_text(encoding="utf-8"), out)
        run("new", "assignment", "hw2", "--parent", "algorithms", "--title", "HW 2", "--kind", "exam",
            "--due", "2000-01-01", "--summary", "Same due date.")
        rc, out = run("status")
        check("status survives assignments sharing a due date", rc == 0 and "algorithms-hw2" in out, out)
        rc, out = run("log", "lint", "x", "--date", "2026-02-30")
        check("log rejects impossible dates", rc == 2, out)
        rc, out = run("project", "ignore", str(outside / "sandbox"))
        check("project ignore takes a positional path",
              str((outside / "sandbox").resolve()) in (tmp / "_system/ignored-repos.txt").read_text(encoding="utf-8"), out)
        rc, out = run("hook", "session-start", stdin=hin())
        check("session-start injects project context", "<project-wiki-context>" in out and "Demo App" in out, out)
        rc, out = run("hook", "session-start", stdin=hin(cwd=str(tmp / "wiki")))
        check("global hooks stay silent inside the vault", out.strip() == "", out)
        md = tmp / "clip.md"
        md.write_text("Body text\n", encoding="utf-8")
        rc, out = run("capture", "--markdown-file", str(md), "--title", "My Clip!", "--url", "https://x.test/a")
        check("capture writes dated raw file", rc == 0 and "raw/" in out and "my-clip" in out, out)
        rc2, out2 = run("capture", "--markdown-file", str(md), "--title", "My Clip!")
        check("capture never overwrites", rc2 == 0 and out2.strip() != out.strip(), out2)
        # guard hook
        guard = real_root / ".claude" / "hooks" / "protect_raw.py"
        if guard.exists():
            genv = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp))

            def g(tool, ti):
                r = subprocess.run([sys.executable, str(guard)], input=json.dumps(
                    {"tool_name": tool, "tool_input": ti, "cwd": str(tmp)}), capture_output=True, text=True, env=genv)
                return r.returncode
            existing = str(tmp / "raw" / "2026-01-01-paper.md")
            check("guard blocks Edit on existing raw file", g("Edit", {"file_path": existing}) == 2)
            check("guard blocks Write over existing raw file", g("Write", {"file_path": existing}) == 2)
            check("guard allows Write of NEW raw file", g("Write", {"file_path": str(tmp / "raw/new.md")}) == 0)
            check("guard allows wiki edits", g("Edit", {"file_path": str(tmp / "wiki/hot.md")}) == 0)
            check("guard blocks rm in raw", g("Bash", {"command": "rm raw/2026-01-01-paper.md"}) == 2)
            check("guard blocks sed -i in raw", g("Bash", {"command": "sed -i '' 's/a/b/' raw/2026-01-01-paper.md"}) == 2)
            check("guard blocks redirect onto raw file", g("Bash", {"command": "echo x > raw/2026-01-01-paper.md"}) == 2)
            check("guard allows reading raw", g("Bash", {"command": "cat raw/2026-01-01-paper.md | head -5"}) == 0)
            check("guard allows new capture via curl -o",
                  g("Bash", {"command": "curl -L -o raw/2026-02-02-new.pdf https://x.test/a.pdf"}) == 0)
            check("guard blocks curl -o over existing",
                  g("Bash", {"command": "curl -L -o raw/2026-01-01-paper.md https://x.test"}) == 2)
            check("guard allows cp out of raw", g("Bash", {"command": "cp raw/2026-01-01-paper.md /tmp/x.md"}) == 0)
            check("guard blocks mv out of raw", g("Bash", {"command": "mv raw/2026-01-01-paper.md /tmp/"}) == 2)
            graw = lambda cmd: subprocess.run([sys.executable, str(guard)], input=json.dumps(
                {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(tmp / "raw")}),
                capture_output=True, text=True, env=genv).returncode
            check("guard blocks relative rm when cwd is raw/", graw("rm 2026-01-01-paper.md") == 2)
            check("guard blocks redirect after cd into raw",
                  g("Bash", {"command": "cd raw && echo x >> 2026-01-01-paper.md"}) == 2)
            check("guard blocks mv onto an existing name in raw/",
                  g("Bash", {"command": "mv /tmp/2026-01-01-paper.md raw/"}) == 2)
        else:
            results.append(("guard hook tests skipped (.claude/hooks/protect_raw.py not found)", True, ""))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if "outside" in locals():
            shutil.rmtree(outside, ignore_errors=True)
    ok = all(r[1] for r in results)
    for name, passed, detail in results:
        print("%s  %s" % ("PASS" if passed else "FAIL", name))
        if not passed and detail:
            print("      " + detail.strip().replace("\n", "\n      ")[:1500])
    print("\nselftest: %s (%d/%d)" % ("OK" if ok else "FAILED", sum(r[1] for r in results), len(results)))
    return 0 if ok else 1


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="wiki.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("status"); p.add_argument("--hook", action="store_true"); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("pending"); p.set_defaults(fn=cmd_pending)
    p = sub.add_parser("search"); p.add_argument("query"); p.add_argument("-n", type=int, default=10)
    p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_search)
    p = sub.add_parser("new"); p.add_argument("type"); p.add_argument("slug"); p.add_argument("--title", required=True)
    p.add_argument("--raw"); p.add_argument("--kind"); p.add_argument("--summary"); p.add_argument("--question")
    p.add_argument("--parent"); p.add_argument("--repo"); p.add_argument("--due"); p.add_argument("--severity")
    p.set_defaults(fn=cmd_new)
    p = sub.add_parser("touch"); p.add_argument("slugs", nargs="+"); p.set_defaults(fn=cmd_touch)
    p = sub.add_parser("index"); p.add_argument("--check", action="store_true"); p.set_defaults(fn=cmd_index)
    p = sub.add_parser("lint"); p.add_argument("--json", action="store_true")
    p.add_argument("--exit-zero", action="store_true"); p.add_argument("--fix", action="store_true")
    p.set_defaults(fn=cmd_lint)
    p = sub.add_parser("rename"); p.add_argument("old"); p.add_argument("new")
    p.add_argument("--dry-run", action="store_true"); p.set_defaults(fn=cmd_rename)
    p = sub.add_parser("log"); p.add_argument("op"); p.add_argument("title")
    p.add_argument("--created", nargs="*"); p.add_argument("--updated", nargs="*")
    p.add_argument("--note", action="append"); p.add_argument("--date"); p.set_defaults(fn=cmd_log)
    p = sub.add_parser("capture")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--defuddle-json"); g.add_argument("--markdown-file"); g.add_argument("--binary")
    p.add_argument("--url"); p.add_argument("--title"); p.add_argument("--author"); p.add_argument("--published")
    p.add_argument("--method"); p.add_argument("--slug"); p.set_defaults(fn=cmd_capture)
    p = sub.add_parser("project"); p.add_argument("action", choices=["add", "which", "list", "ignore"])
    p.add_argument("slug", nargs="?"); p.add_argument("--title"); p.add_argument("--summary")
    p.add_argument("--repo"); p.add_argument("--path"); p.add_argument("--stack", nargs="*")
    p.set_defaults(fn=cmd_project)
    p = sub.add_parser("worklog"); p.add_argument("title"); p.add_argument("--project"); p.add_argument("--cwd")
    p.add_argument("--did", action="append"); p.add_argument("--files", nargs="*"); p.add_argument("--issue", action="append")
    p.add_argument("--next", action="append"); p.add_argument("--note", action="append"); p.add_argument("--session")
    p.set_defaults(fn=cmd_worklog)
    p = sub.add_parser("idea"); p.add_argument("text"); p.add_argument("--project"); p.add_argument("--cwd")
    p.add_argument("--detail", action="append"); p.set_defaults(fn=cmd_idea)
    p = sub.add_parser("issue"); p.add_argument("title"); p.add_argument("--summary", required=True)
    p.add_argument("--project"); p.add_argument("--cwd"); p.add_argument("--slug")
    p.add_argument("--severity", default="medium"); p.add_argument("--status", default="open")
    p.set_defaults(fn=cmd_issue)
    p = sub.add_parser("context"); p.add_argument("--cwd"); p.add_argument("--project"); p.add_argument("--session")
    p.set_defaults(fn=cmd_context)
    p = sub.add_parser("hook"); p.add_argument("event", choices=["session-start", "stop", "session-end"])
    p.set_defaults(fn=cmd_hook)
    p = sub.add_parser("commit"); p.add_argument("message"); p.set_defaults(fn=cmd_commit)
    p = sub.add_parser("install-global"); p.add_argument("--uninstall", action="store_true")
    p.add_argument("--dry-run", action="store_true"); p.set_defaults(fn=cmd_install_global)
    p = sub.add_parser("graphify"); p.add_argument("action", nargs="?", choices=["on", "off", "gaps"])
    p.add_argument("--graph"); p.add_argument("-n", type=int, default=25)
    p.set_defaults(fn=cmd_graphify)
    p = sub.add_parser("selftest"); p.set_defaults(fn=cmd_selftest)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
