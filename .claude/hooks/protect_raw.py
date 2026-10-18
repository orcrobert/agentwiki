#!/usr/bin/env python3
"""PreToolUse hook: raw/ is append-only.

Allowed: creating NEW files in raw/ (captures). Blocked: editing, overwriting,
moving, renaming or deleting EXISTING files in raw/ — via Edit/Write tools or
common shell commands. Exit 2 blocks the call and shows stderr to Claude.

Best-effort for shell commands (it parses common verbs, redirects and -o
flags); git history is the real safety net. Fails open on internal errors so a
bug here never blocks normal work.
"""
import json
import os
import re
import shlex
import sys

MSG = ("raw/ is immutable: existing sources must never be edited, overwritten, moved or deleted "
       "(they are the ground truth the wiki cites). Write derived content to wiki/ instead. "
       "To capture something new, create a NEW dated file in raw/ (python3 _system/wiki.py capture …). "
       "If a raw file truly must change (e.g. to redact a secret), ask the human to do it in Obsidian.")

DESTRUCTIVE = {"rm", "rmdir", "unlink", "shred", "truncate", "chmod", "chown", "mv",
               "Remove-Item", "Move-Item", "Rename-Item", "Set-Content", "Clear-Content", "Add-Content"}
INPLACE = {"sed", "perl", "ruby"}
WRAPPERS = {"sudo", "command", "builtin", "nohup", "time", "nice", "timeout", "env", "xargs", "noglob"}


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    cwd = data.get("cwd") or root
    raw_dir = os.path.realpath(os.path.join(root, "raw"))
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}

    state = {"cwd": cwd}  # tracks `cd` inside compound shell commands

    def absolute(p):
        p = os.path.expanduser(str(p).strip().strip("\"'"))
        if not os.path.isabs(p):
            p = os.path.join(state["cwd"], p)
        return os.path.realpath(p)

    def in_raw(p):
        a = absolute(p)
        return a == raw_dir or a.startswith(raw_dir + os.sep)

    def existing_in_raw(p):
        a = absolute(p)
        return (a.startswith(raw_dir + os.sep)) and os.path.exists(a)

    def block(detail):
        sys.stderr.write("Blocked: %s\n%s\n" % (detail, MSG))
        return 2

    if tool in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
        p = ti.get("file_path") or ti.get("notebook_path") or ""
        if p and in_raw(p):
            if tool == "Write" and not os.path.exists(absolute(p)):
                return 0  # new capture
            return block("%s on %s" % (tool, p))
        return 0

    if tool not in ("Bash", "PowerShell"):
        return 0
    cmd = ti.get("command") or ""
    if "raw" not in cmd:
        return 0

    # redirects: > file, >> file, &> file, 2> file
    for m in re.finditer(r"(?:^|[^<>&0-9])(?:[0-9]?|&)>>?\s*(\"[^\"]+\"|'[^']+'|[^\s;&|()<>]+)", cmd):
        if existing_in_raw(m.group(1)):
            return block("redirect into %s" % m.group(1))

    for seg in re.split(r"\|\||&&|;|\||\n", cmd):
        seg = seg.strip()
        if not seg:
            continue
        try:
            toks = shlex.split(seg, posix=True)
        except ValueError:
            toks = seg.split()
        while toks and (toks[0] in WRAPPERS or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0])):
            toks = toks[1:]
        if not toks:
            continue
        verb = os.path.basename(toks[0])
        args = toks[1:]
        if verb in ("cd", "pushd", "Set-Location") and args:
            state["cwd"] = absolute(args[-1])
            continue
        if verb == "git" and args and args[0] in ("rm", "mv"):
            verb, args = args[0], args[1:]
        raw_args = [a for a in args if not a.startswith("-") and in_raw(a)]
        if verb in DESTRUCTIVE:
            if verb in ("mv", "Move-Item", "Rename-Item") and len([a for a in args if not a.startswith("-")]) >= 2:
                paths = [a for a in args if not a.startswith("-")]
                srcs, dest = paths[:-1], paths[-1]
                if any(in_raw(s) for s in srcs):
                    return block("%s moves a file out of/within raw/" % verb)
                if existing_in_raw(dest) and not os.path.isdir(absolute(dest)):
                    return block("%s overwrites %s" % (verb, dest))
                continue
            if raw_args:
                return block("%s %s" % (verb, " ".join(raw_args)))
        if verb in INPLACE and any(re.match(r"^-[A-Za-z]*i", a) for a in args) and raw_args:
            return block("in-place edit (%s -i) of %s" % (verb, " ".join(raw_args)))
        if verb in ("cp", "install", "rsync", "ditto", "Copy-Item"):
            paths = [a for a in args if not a.startswith("-")]
            if len(paths) >= 2:
                dest = paths[-1]
                if existing_in_raw(dest) and not os.path.isdir(absolute(dest)):
                    return block("%s overwrites %s" % (verb, dest))
                if os.path.isdir(absolute(dest)) and in_raw(dest):
                    for s in paths[:-1]:
                        if os.path.exists(os.path.join(absolute(dest), os.path.basename(s))):
                            return block("%s overwrites %s/%s" % (verb, dest, os.path.basename(s)))
        if verb == "tee":
            for a in args:
                if not a.startswith("-") and existing_in_raw(a):
                    return block("tee into %s" % a)
        # -o FILE / -O FILE / --output FILE / --output=FILE / --output-document=FILE
        for i, a in enumerate(args):
            target = None
            if a in ("-o", "-O", "--output", "--output-document", "-OutFile") and i + 1 < len(args):
                target = args[i + 1]
            elif a.startswith(("--output=", "--output-document=")):
                target = a.split("=", 1)[1]
            if target and existing_in_raw(target):
                return block("%s would overwrite %s" % (verb, target))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # fail open
        sys.stderr.write("protect_raw hook error (allowing): %s\n" % exc)
        sys.exit(0)
