#!/usr/bin/env python3
"""SessionEnd hook: autosave — commit any uncommitted vault changes so no
session's work is ever lost and every session is revertable with git.
Never pushes. Silently does nothing outside a git repo. Always exits 0."""
import datetime
import os
import subprocess
import sys


def git(root, *args):
    return subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True, timeout=15)


def main():
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    if not os.path.isdir(os.path.join(root, ".git")):
        return 0
    if os.environ.get("WIKI_AUTOSAVE", "1") == "0":
        return 0
    gd = os.path.join(root, ".git")
    if any(os.path.exists(os.path.join(gd, n))
           for n in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD")):
        return 0  # never conclude a merge/rebase the human is in the middle of
    if git(root, "diff", "--name-only", "--diff-filter=U").stdout.strip():
        return 0
    st = git(root, "status", "--porcelain")
    if st.returncode != 0 or not st.stdout.strip():
        return 0
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "wiki: autosave at session end (%s)" % stamp)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
