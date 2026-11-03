"""Lab data read by both apps: course catalog, questions with sample cases, lab/control.json and
the teacher's public key.

control.json and the key change during a lab (the "Lab session control" workflow commits them),
so they are read from GitHub (raw.githubusercontent.com) by the app server, not by every
browser: one request per TTL for the whole class instead of one per student per minute. The
copy in the app's own checkout is the fallback. Questions come from the checkout first and from
GitHub when a question was committed after the app last updated.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from . import ROOT
import control as ctl  # tools/lab/control.py

REPO = os.environ.get("LAB_REPO", "parthibanlogan/JAVA")
BRANCH = os.environ.get("LAB_BRANCH", "main")
RAW = "https://raw.githubusercontent.com/%s/%s/" % (REPO, BRANCH)
ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
DEFAULT_REGNO = r"^[0-9]{2}[A-Z]{3}[0-9]{4}$"


@dataclass
class Question:
    id: str
    title: str
    markdown: str
    cases: list                      # [(input, expected)]
    folder: str = ""                 # local folder (setup.sql of Experiment 16), "" when fetched
    kind: str = "lab"                # lab | lesson | experiment
    note: str = ""
    requires: str = ""
    files: dict = field(default_factory=dict)   # reference sources (course programs only)


# ---------------------------------------------------------------------- small cached fetcher
_cache = {}
_cache_lock = threading.Lock()


def fetch_text(path, ttl):
    """Text of a repository file from GitHub, cached ttl seconds; None when missing or offline."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(path)
        if hit and now - hit[0] < ttl:
            return hit[1]
    try:
        req = urllib.request.Request(RAW + path, headers={"User-Agent": "java-lab-streamlit", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=10) as r:
            text = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code != 404:                      # rate limit or outage: keep what we had
            return hit[1] if hit else None
        text = None                            # the file does not exist (cached as such)
    except (urllib.error.URLError, OSError, UnicodeDecodeError):
        return hit[1] if hit else None
    with _cache_lock:
        _cache[path] = (now, text)
    return text


def local_text(path):
    p = os.path.join(ROOT, path)
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


# ---------------------------------------------------------------------- control.json and key
def control(ttl=20):
    """(data, source): lab/control.json from GitHub (fresh within ttl s) or the local copy."""
    text = fetch_text("lab/control.json", ttl)
    source = "GitHub"
    if text is None:
        text, source = local_text("lab/control.json"), "local copy"
    try:
        data = json.loads(text) if text else ctl.empty()
    except ValueError:
        data, source = ctl.empty(), "unreadable"
    data.setdefault("sessions", [])
    data.setdefault("settings", {})
    return data, source


def public_key(ttl=60):
    text = fetch_text("lab/teacher-public-key.pem", ttl) or local_text("lab/teacher-public-key.pem")
    return text if text and "BEGIN PUBLIC KEY" in text else None


def regno_pattern(data):
    try:
        return re.compile((data.get("settings") or {}).get("regnoPattern") or DEFAULT_REGNO)
    except re.error:
        return re.compile(DEFAULT_REGNO)


def utcnow():
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc)


def open_sessions(data, now=None):
    """[(session, window)] open now, by the same rule as intake and gradebook."""
    return ctl.open_windows(data, now or utcnow())


def window_end(w):
    return ctl.window_end(w)


# ---------------------------------------------------------------------- course catalog
def _props(path):
    out = {}
    text = local_text(os.path.relpath(path, ROOT)) or ""
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _cases_in(folder):
    cases, n = [], 1
    while True:
        suf = "" if n == 1 else "-%d" % n
        exp = os.path.join(folder, "expected%s.txt" % suf)
        if not os.path.exists(exp):
            return cases
        inp = os.path.join(folder, "input%s.txt" % suf)
        with open(exp, encoding="utf-8") as f:
            e = f.read()
        i = ""
        if os.path.exists(inp):
            with open(inp, encoding="utf-8") as f:
                i = f.read()
        cases.append((i, e))
        n += 1


_catalog = None


def catalog():
    """Course programs in order: [{"id", "title", "kind", "folder", "requires", "order"}]."""
    global _catalog
    if _catalog is None:
        items = []
        for group in ("lessons", "experiments"):
            base = os.path.join(ROOT, "course", group)
            if not os.path.isdir(base):
                continue
            for d in sorted(os.listdir(base)):
                folder = os.path.join(base, d)
                meta = os.path.join(folder, "meta.properties")
                if os.path.exists(meta):
                    m = _props(meta)
                    items.append({"id": d.split("-")[0], "title": m.get("title", d), "kind": m.get("kind", group[:-1]),
                                  "folder": folder, "requires": m.get("requires", ""),
                                  "order": (0 if group == "lessons" else 1, int(m.get("order", "0") or 0))})
        items.sort(key=lambda x: x["order"])
        _catalog = items
    return _catalog


def course_ids():
    return [p["id"] for p in catalog()]


def question(qid):
    """Question by id: a course program (L07, E05a) or lab/questions/<ID>. None when unknown."""
    if not ID.match(qid or ""):
        return None
    p = next((x for x in catalog() if x["id"] == qid), None)
    if p:
        folder = p["folder"]
        md = local_text(os.path.relpath(os.path.join(folder, "README.md"), ROOT)) or "# " + p["title"]
        files = {}
        for f in sorted(os.listdir(folder)):
            if f.endswith(".java"):
                files[f] = local_text(os.path.relpath(os.path.join(folder, f), ROOT)) or ""
        note = ""
        if p["requires"] == "mysql":
            note = ("This program uses a database. Here it runs against an in-memory database in MySQL mode that "
                    "setup.sql prepares for every run; the gradebook marks it on the real JDK as usual.")
        return Question(qid, p["title"], md, _cases_in(folder), folder, p["kind"], note, p["requires"], files)
    base = "lab/questions/%s/" % qid
    folder = os.path.join(ROOT, base)
    if os.path.isfile(os.path.join(folder, "README.md")):
        md = local_text(base + "README.md")
        cases = _cases_in(folder)
    else:
        md = fetch_text(base + "README.md", 60)
        if md is None:
            return None
        folder, cases = "", []
        for n in range(1, 11):
            suf = "" if n == 1 else "-%d" % n
            exp = fetch_text(base + "expected%s.txt" % suf, 60)
            if exp is None:
                break
            cases.append((fetch_text(base + "input%s.txt" % suf, 60) or "", exp))
    m = re.search(r"^#\s+(.+)$", md or "", re.M)
    return Question(qid, m.group(1).strip() if m else qid, md or "", cases, folder, "lab")


def question_title(qid):
    q = question(qid)
    return q.title if q else qid
