"""Java Lab, student app (Streamlit Community Cloud).

Students type a program (pasting and dropping are blocked and recorded, as on the website's Lab
page), run and check it on the real JDK 21 on the server, and submit an encrypted package as a
GitHub issue. The package has the website's format, so the intake robot and the private gradebook
treat both alike. The app holds no secret: it encrypts with the teacher's PUBLIC key only.

    streamlit run apps/student/app.py          (from the repository root)
"""
import datetime as dt
import hashlib
import os
import shutil
import sys
import urllib.parse

import streamlit as st
import streamlit.components.v1 as components

APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(APP))
from labcore import ROOT, labdata, sandbox  # noqa: E402
from labcore.jdk import VERSION as JDK_VERSION, cache_dir  # noqa: E402
import activity  # noqa: E402  tools/lab/activity.py
import labcrypto  # noqa: E402  tools/lab/labcrypto.py

FORMAT = 1
MAX_ARMOUR = 60000             # a GitHub issue body holds 65 536 characters (same as lab.js)

st.set_page_config(page_title="Java Lab", page_icon=":material/terminal:", layout="wide")


# ---------------------------------------------------------------------- shared resources
@st.cache_resource(show_spinner=False)
def toolchain():
    return sandbox.Toolchain(print)


@st.cache_resource(show_spinner=False)
def editor_component():
    """The editor folder plus Ace and lab-activity.js from the website (one source of truth)."""
    build = os.path.join(cache_dir(), "editor-component")
    shutil.rmtree(build, ignore_errors=True)
    shutil.copytree(os.path.join(APP, "editor"), build)
    os.makedirs(os.path.join(build, "ace"), exist_ok=True)
    ace = os.path.join(ROOT, "site", "assets", "vendor", "ace")
    for f in ("ace.js", "mode-java.js", "theme-chrome.js", "theme-tomorrow_night.js", "LICENSE"):
        shutil.copy(os.path.join(ace, f), os.path.join(build, "ace", f))
    shutil.copy(os.path.join(ROOT, "site", "assets", "js", "lab-activity.js"), os.path.join(build, "lab-activity.js"))
    return components.declare_component("java_lab_editor", path=build)


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ist(t):
    return t.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime("%H:%M")


ss = st.session_state
ss.setdefault("ident", None)
ss.setdefault("ident_req", {"action": "load", "nonce": "load"})
ss.setdefault("processed", set())
ss.setdefault("results", {})
ss.setdefault("last_run", {})
ss.setdefault("last_check", {})
ss.setdefault("server_log", {})
ss.setdefault("packages", {})

editor = editor_component()

# ---------------------------------------------------------------------- identity (kept in the browser)
stored = editor(mode="identity", action=ss.ident_req["action"], identity=ss.ident_req.get("identity"),
                nonce=ss.ident_req["nonce"], key="identity-store", default=None)
if stored and stored.get("nonce") == "load" and ss.ident is None and stored.get("identity") and not ss.get("ident_loaded"):
    ss.ident_loaded = True
    cand = stored["identity"]
    if isinstance(cand, dict) and cand.get("regno") and cand.get("name"):
        ss.ident = {"regno": str(cand["regno"])[:20], "name": str(cand["name"])[:80]}

control, source = labdata.control()
pattern = labdata.regno_pattern(control)
open_now = labdata.open_sessions(control)

with st.sidebar:
    st.subheader("Student")
    with st.form("identity"):
        regno = st.text_input("Register number", value=(ss.ident or {}).get("regno", ""), placeholder="24BCL0123")
        name = st.text_input("Full name", value=(ss.ident or {}).get("name", ""))
        if st.form_submit_button("Start" if not ss.ident else "Change", type="primary"):
            regno = "".join(regno.split()).upper()
            name = " ".join(name.split())
            if not pattern.fullmatch(regno):
                st.error("Register number must look like 24BCL0123.")
            elif len(name) < 3:
                st.error("Enter your full name.")
            else:
                ss.ident = {"regno": regno, "name": name}
                ss.ident_req = {"action": "save", "identity": ss.ident, "nonce": "save-" + os.urandom(4).hex()}
                st.rerun()
    if ss.ident:
        st.caption("Working as **%s** %s" % (ss.ident["regno"], ss.ident["name"]))
        if st.button("Remove my work from this computer", help="Use this on a shared PC before you leave."):
            ss.ident_req = {"action": "forget", "identity": ss.ident, "nonce": "forget-" + os.urandom(4).hex()}
            ss.ident = None
            for k in ("results", "last_run", "last_check", "server_log", "packages"):
                ss[k] = {}
            st.rerun()
    st.divider()
    st.caption("Programs run on Java %s (Eclipse Temurin), the same JDK the teacher marks with. "
               "Lab status read from %s." % (JDK_VERSION, source))

# ---------------------------------------------------------------------- banner
st.title("Java Lab")
if open_now:
    lines = []
    for s, w in open_now:
        end = labdata.window_end(w)
        lines.append("**%s is OPEN**%s%s" % (s["id"], (": " + s["title"]) if s.get("title") else "",
                                              " (closes automatically at %s IST)" % ist(end) if end else " (until the teacher closes it)"))
    st.success("  \n".join(lines) + "  \nThe time GitHub records when you create the issue decides whether it is accepted.")
else:
    st.info("No assessment is open now. You can practise any program; submissions open during the lab hour.")

try:
    with st.spinner("Preparing Java 21 on the server (the first start after a pause takes about a minute)..."):
        tc = toolchain()
except Exception as e:  # noqa: BLE001
    st.error("Java could not be prepared on the server: %s. Reload the page in a minute." % e)
    st.stop()

if not ss.ident:
    st.write("Enter your register number and full name in the sidebar and press **Start**.")
    st.stop()

# ---------------------------------------------------------------------- mode and question
modes = [s["id"] for s, _ in open_now] + ["practice"]
labels = {s["id"]: "%s%s (open)" % (s["id"], (": " + s["title"]) if s.get("title") else "") for s, _ in open_now}
labels["practice"] = "Practice (no submission)"
c1, c2 = st.columns([1, 2])
with c1:
    mode = st.selectbox("Assessment", modes, format_func=lambda m: labels[m], key="mode")
if mode == "practice":
    local_q = sorted(d for d in os.listdir(os.path.join(ROOT, "lab", "questions"))
                     if os.path.isfile(os.path.join(ROOT, "lab", "questions", d, "README.md")))
    qids = labdata.course_ids() + local_q
else:
    qids = list(next(s for s, _ in open_now if s["id"] == mode).get("questions", []))
with c2:
    qid = st.selectbox("Question", qids, format_func=lambda q: "%s: %s" % (q, labdata.question_title(q)), key="qid:" + mode)
q = labdata.question(qid) if qid else None
if q is None:
    st.error("Question %s was not found (lab/questions/%s)." % (qid, qid))
    st.stop()

work_key = "lab-work:%s:%s:%s" % (ss.ident["regno"], mode, q.id)
session_obj = labdata.ctl.find(control, mode) if mode != "practice" else None
is_open = bool(session_obj and any(labdata.ctl.in_window(w, labdata.utcnow()) for w in session_obj.get("windows", [])))
key_pem = labdata.public_key() if mode != "practice" else None
hint = ("Practice work is not submitted." if mode == "practice" else
        "This assessment is closed." if not is_open else
        "The teacher has not published the submission key yet." if not key_pem else "")

left, right = st.columns([5, 6], gap="large")
with left:
    st.subheader(q.title)
    if q.note:
        st.warning(q.note)
    body = q.markdown
    if body.lstrip().startswith("# "):                      # the title is shown above
        body = body.lstrip().split("\n", 1)[1] if "\n" in body.lstrip() else ""
    st.markdown(body)
    for i, (inp, exp) in enumerate(q.cases, 1):
        with st.expander("Sample case %d" % i, expanded=i == 1):
            st.caption("Input")
            st.code(inp or "(none)", language=None)
            st.caption("Expected output")
            st.code(exp, language=None)

with right:
    value = editor(mode="editor", workKey=work_key, defaultStdin=q.cases[0][0] if q.cases else "",
                   caseCount=len(q.cases), submitOpen=not hint, submitHint=hint,
                   confirmText="Submit %s for %s as %s %s?" % (q.id, mode, ss.ident["regno"], ss.ident["name"]),
                   result=ss.results.get(work_key), height=420, key="editor:" + work_key, default=None)
    out = st.container()


# ---------------------------------------------------------------------- actions
def log(action, code, outcome):
    ss.server_log.setdefault(work_key, []).append([now_iso(), action, activity.fnv(code), outcome])
    del ss.server_log[work_key][:-200]


def compile_or_report(files, code):
    c = tc.compile(files)
    if not c.ok:
        log("compile", code, "compile-error")
    return c


def do_run(v):
    code = v["code"]
    files = {sandbox.file_name_for(code): code}
    c = compile_or_report(files, code)
    try:
        if not c.ok:
            return {"event": ["x", "compile-error", c.ms], "kind": "bad", "message": "The program does not compile.",
                    "view": {"type": "compile", "text": c.text()}}
        r = tc.run(c, v.get("stdin", ""), setup_sql=sandbox.setup_sql_for(q.folder))
    except TimeoutError as e:
        return {"event": None, "kind": "warn", "message": str(e), "view": None}
    finally:
        c.cleanup()
    log("run", code, r.outcome)
    ss.last_run[work_key] = {"at": now_iso(), "outcome": r.outcome, "ms": r.ms, "stdin": v.get("stdin", "")[:2000],
                             "stdout": r.stdout[:4000]}
    return {"event": ["x", r.outcome, r.ms], "kind": "" if r.outcome == "ok" else "warn",
            "message": "Finished in %d ms" % r.ms if r.outcome == "ok" else "Stopped: %s" % r.outcome,
            "view": {"type": "run", "stdout": r.stdout, "stderr": r.stderr, "timed_out": r.timed_out,
                     "limited": r.output_limited, "files": r.files, "exit": r.exit_code}}


def do_check(v):
    code = v["code"]
    files = {sandbox.file_name_for(code): code}
    c = compile_or_report(files, code)
    try:
        if not c.ok:
            return {"event": ["x", "compile-error", 0], "kind": "bad", "message": "The program does not compile.",
                    "view": {"type": "compile", "text": c.text()}}
        rows, passed = [], 0
        for inp, exp in q.cases:
            r = tc.run(c, inp, setup_sql=sandbox.setup_sql_for(q.folder))
            ok = not r.timed_out and sandbox.normalise(r.stdout) == sandbox.normalise(exp)
            passed += ok
            rows.append({"ok": ok, "input": inp, "expected": exp, "stdout": r.stdout, "stderr": r.stderr,
                         "timed_out": r.timed_out})
    except TimeoutError as e:
        return {"event": None, "kind": "warn", "message": str(e), "view": None}
    finally:
        c.cleanup()
    total = len(q.cases)
    log("check", code, "%d/%d" % (passed, total))
    ss.last_check[work_key] = {"at": now_iso(), "passed": passed, "total": total}
    return {"event": ["c", passed, total], "kind": "" if passed == total else "warn",
            "message": "%d of %d sample cases passed." % (passed, total), "view": {"type": "check", "rows": rows}}


def do_submit(v):
    control_now, _ = labdata.control(ttl=5)
    s = labdata.ctl.find(control_now, mode)
    if not s or not any(labdata.ctl.in_window(w, labdata.utcnow()) for w in s.get("windows", [])):
        return {"event": None, "kind": "bad", "message": "This assessment is not open now.", "view": None}
    pem = labdata.public_key(ttl=5)
    if not pem:
        return {"event": None, "kind": "bad", "message": "The teacher has not published the submission key yet.", "view": None}
    code = v["code"]
    events = v.get("events") or []
    payload = {
        "format": FORMAT, "kind": "lab-submission", "session": mode, "question": q.id,
        "regno": ss.ident["regno"], "name": ss.ident["name"], "files": {sandbox.file_name_for(code): code},
        "createdAt": now_iso(), "timeZone": str(v.get("timeZone", ""))[:64], "userAgent": str(v.get("userAgent", ""))[:300],
        "page": "streamlit:student-app",
        "activity": {"format": FORMAT, "t0": v.get("t0"), "events": events, "trimmed": False},
        "summary": activity.summarise(events, code),
        "lastRun": ss.last_run.get(work_key), "lastCheck": ss.last_check.get(work_key),
        "server": {"app": "apps/student", "jdk": JDK_VERSION, "log": ss.server_log.get(work_key, [])},
    }
    binary = labcrypto.encrypt(payload, pem)
    armour = labcrypto.armour(binary)
    if len(armour) > MAX_ARMOUR:
        payload["activity"] = dict(payload["activity"], events=[e for e in events if e and e[0] not in ("i", "r")], trimmed=True)
        binary = labcrypto.encrypt(payload, pem)
        armour = labcrypto.armour(binary)
    if len(armour) > MAX_ARMOUR:
        return {"event": None, "kind": "bad", "message": "The program is too long to submit (more than about 40 000 characters).",
                "view": None}
    receipt = labcrypto.sha256(binary)[:16]
    log("submit", code, receipt)
    fields = {"template": "lab-submission.yml", "title": "[Lab] %s %s" % (mode, q.id), "session": mode,
              "question": q.id, "receipt": receipt}
    if len(armour) < 5000:
        fields["package"] = armour
    url = "https://github.com/%s/issues/new?%s" % (labdata.REPO, urllib.parse.urlencode(fields))
    mine = "https://github.com/%s/issues?%s" % (labdata.REPO, urllib.parse.urlencode({"q": "is:issue author:@me label:lab-submission"}))
    ss.packages[work_key] = {"armour": armour, "receipt": receipt, "key": labcrypto.key_id(pem), "url": url, "mine": mine}
    return {"event": None, "kind": "", "message": "Package made. Copy it and create the GitHub issue (below).",
            "view": {"type": "submit"}}


if value and value.get("nonce") and value["nonce"] not in ss.processed:
    ss.processed.add(value["nonce"])
    action = value.get("action")
    handler = {"run": do_run, "check": do_check, "submit": do_submit}.get(action)
    if handler and isinstance(value.get("code"), str):
        with out:
            with st.spinner("Working on the server..."):
                res = handler(value)
        res["nonce"] = value["nonce"]
        ss.results[work_key] = res
        st.rerun()

# ---------------------------------------------------------------------- results
res = ss.results.get(work_key)
view = (res or {}).get("view")
with out:
    if view and view["type"] == "compile":
        st.error("The program does not compile.")
        st.code(view["text"], language=None)
    elif view and view["type"] == "run":
        st.caption("Output")
        st.code(view["stdout"] or "(no output)", language=None, wrap_lines=True)
        if view["stderr"]:
            st.error("Error output")
            st.code(view["stderr"], language=None)
        if view["timed_out"]:
            st.warning("Stopped: time limit reached (endless loop, or waiting for more keyboard input than given).")
        if view["limited"]:
            st.warning("Stopped: too much output.")
        if view["files"]:
            with st.expander("Files the program wrote (%d)" % len(view["files"])):
                for name, text in view["files"].items():
                    st.caption(name)
                    st.code(text, language=None)
    elif view and view["type"] == "check":
        rows = view["rows"]
        passed = sum(r["ok"] for r in rows)
        (st.success if passed == len(rows) else st.warning)(
            "%d of %d sample cases passed. The teacher also uses other, hidden cases." % (passed, len(rows)))
        for i, r in enumerate(rows, 1):
            if r["ok"]:
                st.write("Sample case %d: passed" % i)
                continue
            with st.expander("Sample case %d: different output" % i, expanded=True):
                a, b = st.columns(2)
                a.caption("Expected")
                a.code(r["expected"], language=None, wrap_lines=True)
                b.caption("Your program")
                b.code(r["stdout"] or "(no output)", language=None, wrap_lines=True)
                if r["stderr"]:
                    st.code(r["stderr"], language=None)
                if r["timed_out"]:
                    st.warning("Stopped: time limit reached.")
    pkg = ss.packages.get(work_key)
    if pkg and view and view["type"] == "submit":
        st.success("Receipt `%s` (key %s). The reply on GitHub shows the same receipt." % (pkg["receipt"], pkg["key"]))
        st.markdown("1. Copy the package with the copy icon at the top right of the box.\n"
                    "2. Press **Open GitHub**, click in **Package**, paste (Ctrl+V), press **Create**.\n"
                    "3. Wait for the reply on that page: **Accepted** (with the time).")
        st.code(pkg["armour"], language=None, height=180)
        b1, b2 = st.columns(2)
        b1.link_button("Open GitHub", pkg["url"], type="primary")
        b2.link_button("My submissions", pkg["mine"])
