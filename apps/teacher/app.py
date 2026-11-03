"""Java Lab, teacher app (Streamlit Community Cloud, private app).

Everything a lab session needs from one page: open and close assessments, watch submissions
arrive, start the marking in the private gradebook, read the marks and similarity lists, replay
how each program was typed, add new questions with hidden tests, and manage the key pair.

The app never runs student code. It acts on GitHub with a fine-grained token (secrets):
    TEACHER_PASSWORD = "..."                     required
    GITHUB_TOKEN     = "github_pat_..."          required (see apps/labcore/github.py for permissions)
    LAB_REPO         = "parthibanlogan/JAVA"            optional
    GRADEBOOK_REPO   = "parthibanlogan/java-lab-gradebook"  optional

    streamlit run apps/teacher/app.py          (from the repository root)
"""
import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import re
import sys
import time

import streamlit as st

APP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(APP))
from labcore import ROOT, labdata, sandbox  # noqa: E402
from labcore.github import GitHub, GitHubError  # noqa: E402
import activity  # noqa: E402
import control as ctl  # noqa: E402
import labcrypto  # noqa: E402

st.set_page_config(page_title="Java Lab - Teacher", page_icon=":material/school:", layout="wide")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
QID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def secret(name, default=None):
    try:
        v = st.secrets.get(name, default)
    except Exception:  # noqa: BLE001  no secrets file at all (local runs): use the environment
        v = default
    return os.environ.get(name, v) if v in (None, "") else v


def ist(text):
    if not text:
        return ""
    return ctl.parse_time(text).astimezone(IST).strftime("%d %b %H:%M:%S")


# ---------------------------------------------------------------------- sign-in
password = secret("TEACHER_PASSWORD")
if not password:
    st.error("Set TEACHER_PASSWORD (and GITHUB_TOKEN) in this app's secrets: Manage app, Settings, Secrets. "
             "See docs/11-streamlit-apps.md.")
    st.stop()
ss = st.session_state
ss.setdefault("auth", False)
ss.setdefault("fails", 0)
if not ss.auth:
    st.title("Java Lab - Teacher")
    with st.form("login"):
        pw = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", type="primary"):
            if ss.fails >= 5:
                time.sleep(5)
            if hmac.compare_digest(hashlib.sha256(pw.encode()).digest(), hashlib.sha256(str(password).encode()).digest()):
                ss.auth = True
                ss.fails = 0
                st.rerun()
            ss.fails += 1
            st.error("Wrong password.")
    st.stop()

TOKEN = secret("GITHUB_TOKEN")
LAB = secret("LAB_REPO", labdata.REPO)
GRADEBOOK = secret("GRADEBOOK_REPO", LAB.split("/")[0] + "/java-lab-gradebook")
if not TOKEN:
    st.error("Set GITHUB_TOKEN in this app's secrets (docs/11-streamlit-apps.md).")
    st.stop()
gh = GitHub(TOKEN)


@st.cache_resource(show_spinner=False)
def toolchain():
    return sandbox.Toolchain(print)


@st.cache_data(ttl=10, show_spinner=False)
def text_of(repo, path):
    return gh.file_text(repo, path)


@st.cache_data(ttl=30, show_spinner=False)
def tree_of(repo):
    return gh.tree(repo)


@st.cache_data(ttl=15, show_spinner=False)
def runs_of(repo, workflow):
    return gh.runs(repo, workflow, 6)


@st.cache_data(ttl=20, show_spinner=False)
def submissions():
    return gh.issues(LAB, "lab-submission", limit=2000)


def refresh():
    st.cache_data.clear()


def control_data():
    try:
        t = text_of(LAB, "lab/control.json")
    except GitHubError as e:
        st.error("Cannot read lab/control.json of %s: %s. Check GITHUB_TOKEN and LAB_REPO in the secrets." % (LAB, e))
        return ctl.empty()
    try:
        return json.loads(t) if t else ctl.empty()
    except ValueError:
        return ctl.empty()


def show_runs(repo, workflow, title):
    try:
        runs = runs_of(repo, workflow)
    except GitHubError as e:
        st.warning("%s: %s" % (title, e))
        return
    if not runs:
        st.caption("No runs of %s yet." % title)
        return
    rows = [{"started (IST)": ist(r["created_at"]), "status": r["status"], "result": r.get("conclusion") or "",
             "by": (r.get("actor") or {}).get("login", ""), "link": r["html_url"]} for r in runs]
    st.dataframe(rows, hide_index=True, column_config={"link": st.column_config.LinkColumn("link", display_text="open")})


def question_ids():
    ids = list(labdata.course_ids())
    try:
        paths = tree_of(LAB)
        ids += sorted({p.split("/")[2] for p in paths if p.startswith("lab/questions/") and p.endswith("/README.md") and p.count("/") == 3})
    except GitHubError:
        pass
    return ids


# ---------------------------------------------------------------------- page
st.title("Java Lab - Teacher")
c1, c2 = st.columns([4, 1])
c1.caption("Lab repository `%s` (public) and gradebook `%s` (private)." % (LAB, GRADEBOOK))
if c2.button("Refresh", icon=":material/refresh:"):
    refresh()
    st.rerun()

tab_s, tab_sub, tab_m, tab_r, tab_q, tab_k = st.tabs(["Sessions", "Submissions", "Marks", "Replay", "Questions", "Keys"])

# ---------------------------------------------------------------------- sessions
with tab_s:
    data = control_data()
    now = labdata.utcnow()
    rows = []
    for s in data.get("sessions", []):
        w = s.get("windows", [])
        open_ = any(ctl.in_window(x, now) for x in w)
        last = w[-1] if w else {}
        rows.append({"session": s["id"], "state": "OPEN" if open_ else "closed", "title": s.get("title", ""),
                     "questions": " ".join(s.get("questions", [])), "windows": len(w),
                     "last opened (IST)": ist(last.get("opened_at")),
                     "closes (IST)": ist(last.get("closed_at") or last.get("closes_at"))})
    if rows:
        st.dataframe(rows, hide_index=True)
    else:
        st.info("No sessions yet.")
    a, b = st.columns(2)
    with a:
        st.subheader("Open")
        with st.form("open"):
            sid = st.text_input("Session", placeholder="W05 or W05-A", help="1-32 letters, digits, - or _")
            qs = st.multiselect("Questions", question_ids(), help="Empty = keep the session's questions (when reopening).")
            minutes = st.number_input("Close automatically after (minutes, 0 = when you close)", 0, 600, 0, step=5)
            title = st.text_input("Title shown to students (optional)")
            if st.form_submit_button("Open session", type="primary"):
                if not QID.match(sid or ""):
                    st.error("Session name: 1-32 letters, digits, - or _.")
                elif not qs and not ctl.find(data, sid):
                    st.error("A new session needs its questions.")
                else:
                    try:
                        gh.dispatch(LAB, "lab-control.yml", {"action": "open", "session": sid, "questions": " ".join(qs),
                                                             "minutes": str(int(minutes)), "title": title})
                        st.success("Requested. The workflow records the time it starts; status shows below within a minute.")
                        refresh()
                    except GitHubError as e:
                        st.error(str(e))
    with b:
        st.subheader("Close")
        open_ids = [r["session"] for r in rows if r["state"] == "OPEN"]
        with st.form("close"):
            sid = st.selectbox("Session", open_ids + ["(every open session)"])
            if st.form_submit_button("Close", type="primary", disabled=not open_ids):
                try:
                    gh.dispatch(LAB, "lab-control.yml", {"action": "close", "session": "" if sid.startswith("(") else sid,
                                                         "questions": "", "minutes": "0", "title": ""})
                    st.success("Requested. Issues GitHub creates after the workflow starts are rejected.")
                    refresh()
                except GitHubError as e:
                    st.error(str(e))
    st.subheader("Lab session control runs")
    show_runs(LAB, "lab-control.yml", "Lab session control")

# ---------------------------------------------------------------------- submissions
with tab_sub:
    data = control_data()
    sids = [s["id"] for s in data.get("sessions", [])]
    if not sids:
        st.info("No sessions yet.")
    else:
        sid = st.selectbox("Session", sids[::-1], key="sub-session")
        try:
            issues = [i for i in submissions() if i["title"].startswith("[Lab] %s " % sid)]
        except GitHubError as e:
            issues = []
            st.error(str(e))
        rows = []
        for i in issues:
            labels = {x["name"] for x in i.get("labels", [])}
            state = ("ignored" if "lab-ignore" in labels else "accepted" if "lab-accepted" in labels else
                     "late, accepted" if "lab-accept-late" in labels else "rejected" if "lab-rejected" in labels else "waiting")
            rows.append({"issue": i["number"], "github": (i.get("user") or {}).get("login", ""),
                         "question": i["title"].split()[-1], "created (IST)": ist(i["created_at"]), "state": state,
                         "link": i["html_url"]})
        accepted = [r for r in rows if r["state"] in ("accepted", "late, accepted")]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Issues", len(rows))
        m2.metric("Accepted", len(accepted))
        m3.metric("Rejected", sum(r["state"] == "rejected" for r in rows))
        m4.metric("Students (GitHub accounts)", len({r["github"] for r in accepted}))
        per_q = {}
        for r in accepted:
            per_q.setdefault(r["question"], set()).add(r["github"])
        if per_q:
            st.caption("Accounts with an accepted submission, per question: " +
                       ", ".join("%s %d" % (k, len(v)) for k, v in sorted(per_q.items())))
        st.dataframe(rows, hide_index=True, column_config={"link": st.column_config.LinkColumn("link", display_text="open")})
        st.caption("Names and register numbers are inside the encrypted packages; they appear in Marks after collection.")

# ---------------------------------------------------------------------- marks
with tab_m:
    data = control_data()
    sids = [s["id"] for s in data.get("sessions", [])]
    sid = st.selectbox("Session", sids[::-1], key="marks-session") if sids else None
    a, b = st.columns([1, 3])
    if a.button("Collect and mark now", type="primary", disabled=not sid):
        try:
            gh.dispatch(GRADEBOOK, "collect.yml", {"session": sid})
            st.success("Started in the gradebook (3-20 minutes). Press Refresh to see the result.")
            refresh()
        except GitHubError as e:
            st.error("%s (does %s exist, with .github/workflows/collect.yml?)" % (e, GRADEBOOK))
    with b:
        show_runs(GRADEBOOK, "collect.yml", "Collect and mark")
    if sid:
        try:
            readme = text_of(GRADEBOOK, "results/%s/README.md" % sid)
        except GitHubError as e:
            readme = None
            st.error(str(e))
        if readme is None:
            st.info("No results for %s yet." % sid)
        else:
            for name, label in (("marks-wide.csv", "Marks per student"), ("marks.csv", "Every question, tests and typing flags"),
                                ("similarity.csv", "Similar programs (80 %+ shared 5-token sequences)")):
                try:
                    text = text_of(GRADEBOOK, "results/%s/%s" % (sid, name))
                except GitHubError:
                    text = None
                if text:
                    st.subheader(label)
                    rows = list(csv.DictReader(io.StringIO(text)))
                    st.dataframe(rows, hide_index=True) if rows else st.caption("(none)")
                    st.download_button("Download %s" % name, text, file_name="%s-%s" % (sid, name), mime="text/csv",
                                       key="dl-%s-%s" % (sid, name))
            with st.expander("Full report (README.md of the gradebook)"):
                st.markdown(readme)

# ---------------------------------------------------------------------- replay
with tab_r:
    try:
        paths = [p for p in tree_of(GRADEBOOK) if p.startswith("results/") and p.endswith("/submission.json")]
    except GitHubError as e:
        paths = []
        st.error(str(e))
    if not paths:
        st.info("No collected submissions yet (Marks, Collect and mark now).")
    else:
        parts = [p.split("/") for p in paths]          # results/S/Q/REGNO/ISSUE/submission.json
        parts = [x for x in parts if len(x) == 6]
        k1, k2, k3, k4 = st.columns(4)
        s_ = k1.selectbox("Session", sorted({x[1] for x in parts}, reverse=True), key="rp-s")
        q_ = k2.selectbox("Question", sorted({x[2] for x in parts if x[1] == s_}), key="rp-q")
        r_ = k3.selectbox("Register number", sorted({x[3] for x in parts if x[1] == s_ and x[2] == q_}), key="rp-r")
        i_ = k4.selectbox("Issue (attempt)", sorted({x[4] for x in parts if x[1] == s_ and x[2] == q_ and x[3] == r_},
                                                    key=lambda v: int(v) if v.isdigit() else 0, reverse=True), key="rp-i")
        base = "results/%s/%s/%s/%s/" % (s_, q_, r_, i_)
        try:
            raw = text_of(GRADEBOOK, base + "submission.json")
        except GitHubError as e:
            raw = None
            st.error(str(e))
        try:
            sub = json.loads(raw or "{}")
        except ValueError:
            sub = {}
        data_ = sub.get("data", sub)
        files = data_.get("files") or {}
        code = next(iter(files.values()), "")
        act = data_.get("activity") or {}
        events = [e for e in (act.get("events") or []) if isinstance(e, list) and len(e) >= 2]
        summ = activity.summarise(events, code)
        fl = activity.flags(summ, bool(act.get("trimmed")))
        st.write("**%s** %s, issue #%s" % (data_.get("regno", r_), data_.get("name", ""), i_))
        m = st.columns(5)
        m[0].metric("Typed chars", summ["typedChars"])
        m[1].metric("Final chars", summ["finalChars"])
        m[2].metric("Active min", "%.1f" % (summ["activeMs"] / 60000))
        m[3].metric("Runs", summ["runs"])
        m[4].metric("Pastes blocked", summ["pasteBlocked"])
        if fl:
            st.warning("Flags: " + "; ".join(fl))
        if "server" in data_:
            st.caption("Submitted from the Streamlit student app; %d server-side actions logged." % len(data_["server"].get("log", [])))
        end = max([e[1] for e in events] + [0])
        t = st.slider("Time since start (seconds)", 0, max(1, int(end // 1000) + 1), max(1, int(end // 1000) + 1), key="rp-t")
        st.code(activity.replay(events, t * 1000), language="java", line_numbers=True)
        with st.expander("Events up to this time"):
            names = {"i": "typed", "r": "deleted", "p": "PASTE BLOCKED", "P": "internal paste", "B": "LARGE INSERT",
                     "d": "DROP BLOCKED", "a": "left page", "f": "back", "L": "reloaded", "x": "run", "c": "check", "s": "submit"}
            st.dataframe([{"time": "%d:%02d" % (e[1] // 60000, e[1] // 1000 % 60), "event": names.get(e[0], e[0]),
                           "detail": json.dumps(e[2:])[:120]} for e in events if e[1] <= t * 1000][-400:], hide_index=True)
        try:
            res = text_of(GRADEBOOK, base + "result.md")
        except GitHubError:
            res = None
        if res:
            with st.expander("Marking result (hidden cases)"):
                st.markdown(res)

# ---------------------------------------------------------------------- questions
with tab_q:
    st.write("A new question: the statement and sample cases go to the public lab repository (students see them), the "
             "solution and all marking cases to the private gradebook. Expected outputs are made by running your solution "
             "on Java 21 here, so Check, the website and the marking agree.")
    with st.form("question"):
        qid = st.text_input("Question id", placeholder="Q04")
        statement = st.text_area("Statement (Markdown, first line '# Q04 Title')", height=220)
        solution = st.text_area("Reference solution (Main.java)", height=260)
        samples = st.text_area("Sample inputs shown to students: one case per block, blocks separated by a line ---", height=140)
        hidden = st.text_area("Hidden marking inputs (same format; boundaries, invalid and large values)", height=140)
        preview = st.form_submit_button("Run the solution on every case")
    split = lambda t: [b.strip("\n") + "\n" for b in re.split(r"(?m)^---\s*$", t or "") if b.strip()]
    if preview:
        ss.qdraft = None
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", qid or ""):
            st.error("Question id: letters and digits, for example Q04.")
        elif labdata.question(qid) and not qid.startswith("Q"):
            st.error("%s is a course program id." % qid)
        elif not statement.strip().startswith("# "):
            st.error("The statement must start with '# %s Title'." % qid)
        elif not split(samples):
            st.error("Give at least one sample input.")
        else:
            with st.spinner("Preparing Java 21 and running the solution..."):
                tc = toolchain()
                c = tc.compile({sandbox.file_name_for(solution): solution})
                try:
                    if not c.ok:
                        st.error("The solution does not compile.")
                        st.code(c.text(), language=None)
                    else:
                        outs = []
                        for inp in split(samples) + split(hidden):
                            r = tc.run(c, inp)
                            outs.append((inp, r))
                        bad = [r for _, r in outs if r.timed_out or r.exit_code != 0]
                        if bad:
                            st.warning("%d case(s) ended with an error or the time limit: check them." % len(bad))
                        ss.qdraft = {"id": qid, "statement": statement, "solution": solution,
                                     "samples": [(i, r.stdout) for i, r in outs[:len(split(samples))]],
                                     "hidden": [(i, r.stdout) for i, r in outs[len(split(samples)):]]}
                finally:
                    c.cleanup()
    d = ss.get("qdraft")
    if d:
        st.subheader("Preview of %s" % d["id"])
        for kind in ("samples", "hidden"):
            for n, (i, o) in enumerate(d[kind], 1):
                with st.expander("%s %d" % (kind[:-1].capitalize(), n)):
                    x, y = st.columns(2)
                    x.code(i, language=None)
                    y.code(o or "(no output)", language=None)
        public = {"lab/questions/%s/README.md" % d["id"]: d["statement"].rstrip() + "\n"}
        for n, (i, o) in enumerate(d["samples"], 1):
            suf = "" if n == 1 else "-%d" % n
            public["lab/questions/%s/input%s.txt" % (d["id"], suf)] = i
            public["lab/questions/%s/expected%s.txt" % (d["id"], suf)] = o
        private = {"solutions/%s/Main.java" % d["id"]: d["solution"].rstrip() + "\n"}
        for n, (i, o) in enumerate(d["samples"] + d["hidden"], 1):
            private["tests/%s/input-%d.txt" % (d["id"], n)] = i
            private["tests/%s/expected-%d.txt" % (d["id"], n)] = o
        x, y = st.columns(2)
        if x.button("1. Save solution and marking cases in the gradebook", type="primary"):
            try:
                gh.commit_files(GRADEBOOK, private, "Question %s: solution and marking cases" % d["id"])
                st.success("Saved in %s (tests/%s, solutions/%s)." % (GRADEBOOK, d["id"], d["id"]))
            except GitHubError as e:
                st.error(str(e))
        if y.button("2. Publish statement and samples to students"):
            try:
                gh.commit_files(LAB, public, "Question %s: statement and sample cases" % d["id"])
                st.success("Published in lab/questions/%s. Students see it as soon as a session includes it." % d["id"])
                refresh()
            except GitHubError as e:
                st.error(str(e))
        st.caption("Publish shortly before the lab if the question should stay unseen until then; the public repository can be read by anyone.")

# ---------------------------------------------------------------------- keys
with tab_k:
    try:
        pem = text_of(LAB, "lab/teacher-public-key.pem")
    except GitHubError as e:
        pem = None
        st.error(str(e))
    if pem and "BEGIN PUBLIC KEY" in pem:
        st.success("Students' submissions are encrypted for key **%s** (lab/teacher-public-key.pem)." % labcrypto.key_id(pem))
    else:
        st.warning("No public key is published yet: students cannot submit. Create one below.")
    st.write("A new key pair replaces the old one: packages made with the old key are rejected afterwards, and the "
             "gradebook needs the new private key. Do this before the course starts, not during a lab.")
    if st.button("Create a new key pair"):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        ss.newkey = {
            "pub": key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
            "priv": key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()).decode()}
    nk = ss.get("newkey")
    if nk:
        st.info("New key id **%s**. It exists only in this browser tab until you download it." % labcrypto.key_id(nk["pub"]))
        st.download_button("1. Download lab-private-key.pem (keep it safe; never commit it)", nk["priv"],
                           file_name="lab-private-key.pem", mime="application/x-pem-file")
        st.markdown("2. Gradebook secret: [Settings, Secrets and variables, Actions](https://github.com/%s/settings/secrets/actions), "
                    "secret `LAB_PRIVATE_KEY`, value = the whole content of the downloaded file." % GRADEBOOK)
        done = st.checkbox("I downloaded the private key and saved it as the gradebook secret LAB_PRIVATE_KEY")
        if st.button("3. Publish the public key", type="primary", disabled=not done):
            try:
                gh.commit_files(LAB, {"lab/teacher-public-key.pem": nk["pub"]}, "Lab: teacher public key %s" % labcrypto.key_id(nk["pub"]))
                st.success("Published. Students reload the Lab page or app.")
                ss.newkey = None
                refresh()
            except GitHubError as e:
                st.error(str(e))
