#!/usr/bin/env python3
"""Points every address of the original repository (parthiban-loganathan/Java) to yours.

    python3 tools/set_owner.py                 owner/name from `git remote get-url origin`
    python3 tools/set_owner.py OWNER/REPO      explicit

Rewrites the website links, raw.githubusercontent.com, Codespaces and Pages addresses, the
student app's default repository and the gradebook workflow's LAB_REPOSITORY. Safe to run again.
"""
import os
import re
import subprocess
import sys

OLD_OWNER, OLD_REPO = "parthiban-loganathan", "Java"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLUG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")


def from_origin():
    url = subprocess.run(["git", "-C", ROOT, "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if not m:
        raise SystemExit("origin is not a GitHub repository (%r); give OWNER/REPO" % url)
    return m.group(1)


def replacements(owner, repo):
    return [
        ("%s.github.io/%s" % (OLD_OWNER, OLD_REPO), "%s.github.io/%s" % (owner.lower(), repo)),
        ("%s/%s/main/" % (OLD_OWNER, OLD_REPO), "%s/%s/main/" % (owner, repo)),
        ("%s/java-lab-gradebook" % OLD_OWNER, "%s/java-lab-gradebook" % owner),
        ("%s/%s" % (OLD_OWNER, OLD_REPO), "%s/%s" % (owner, repo)),
        ("%s.github.io" % OLD_OWNER, "%s.github.io" % owner.lower()),
    ]


def text_files():
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, text=True).stdout.split("\n")
    files = [f for f in out if f]
    if not files:                                   # not a git checkout: walk the tree
        for base, dirs, names in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "build", "target")]
            files += [os.path.relpath(os.path.join(base, n), ROOT) for n in names]
    return files


def main(argv):
    slug = argv[1] if len(argv) > 1 else from_origin()
    if not SLUG.match(slug):
        raise SystemExit("not a repository name: %r (expected OWNER/REPO)" % slug)
    owner, repo = slug.split("/")
    if (owner, repo) == (OLD_OWNER, OLD_REPO):
        print("Repository is %s already: nothing to change." % slug)
        return 0
    changed = 0
    for rel in text_files():
        path = os.path.join(ROOT, rel)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (UnicodeDecodeError, OSError):
            continue
        new = text
        for a, b in replacements(owner, repo):
            new = new.replace(a, b)
        if new != text and rel != "tools/set_owner.py":
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(new)
            changed += 1
            print("  updated", rel)
    left = []
    for rel in text_files():
        path = os.path.join(ROOT, rel)
        if rel == "tools/set_owner.py" or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="ignore") as f:
            if OLD_OWNER in f.read():
                left.append(rel)
    print("%d files now point to %s." % (changed, slug))
    if left:
        print("Still pointing to the old repository:", ", ".join(left))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
