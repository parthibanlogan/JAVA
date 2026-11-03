"""Both Streamlit apps run headless (streamlit.testing AppTest) against a fake GitHub API.

    python3 -m unittest discover -s apps/tests -v
Student app: identity, practice mode, questions and their sample cases.
Teacher app: password gate, sessions from control.json, open/close dispatch the real workflow with
the right inputs, submissions counted by label, marks and similarity read from the gradebook,
replay of a decrypted submission, a new question run on Java 21 and committed (solution and
hidden cases to the gradebook, statement and samples to the lab repository), key pair publication.
"""
import json
import os
import sys
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = os.path.dirname(HERE)
ROOT = os.path.dirname(APPS)
LAB, BOOK = "owner/Java", "owner/java-lab-gradebook"


class Fake:
    files = {}
    dispatches = []
    commits = []
    pending = {}


def reset():
    sub = {"meta": {"issue": 7}, "regno": "24BCL0001", "name": "Anitha R", "session": "W05", "question": "Q01",
           "files": {"Main.java": "class Main {}"},
           "activity": {"format": 1, "events": [["i", 1000, 0, 0, "class Main {"], ["i", 4000, 0, 12, "}"],
                                                  ["p", 5000, 30, "pasted text"], ["x", 6000, "ok", 120]], "trimmed": False}}
    Fake.files = {
        LAB: {"lab/control.json": json.dumps({"format": 1, "settings": {}, "sessions": [
            {"id": "W04", "title": "", "questions": ["L07"],
             "windows": [{"opened_at": "2026-10-26T09:00:00Z", "closes_at": None, "closed_at": "2026-10-26T11:00:00Z"}]},
            {"id": "W05", "title": "Week 5", "questions": ["Q01", "E05a"],
             "windows": [{"opened_at": "2026-11-02T09:00:00Z", "closes_at": None, "closed_at": None}]}]}),
              "lab/questions/Q01/README.md": "# Q01 Peak runoff\n"},
        BOOK: {"results/W05/README.md": "# Results W05\n",
               "results/W05/marks-wide.csv": "regno,name,Q01,average_percent\n24BCL0001,Anitha R,100,100\n",
               "results/W05/marks.csv": "regno,name,question,tests_passed\n24BCL0001,Anitha R,Q01,6\n",
               "results/W05/similarity.csv": "question,regno_a,regno_b,similarity\n",
               "results/W05/Q01/24BCL0001/7/submission.json": json.dumps(sub),
               "results/W05/Q01/24BCL0001/7/result.md": "6/6 passed\n"},
    }
    Fake.dispatches, Fake.commits, Fake.pending = [], [], {}


ISSUES = [{"number": 7, "title": "[Lab] W05 Q01", "user": {"login": "anitha-r"}, "created_at": "2026-11-02T09:30:00Z",
           "html_url": "https://github.com/owner/Java/issues/7", "labels": [{"name": "lab-submission"}, {"name": "lab-accepted"}]},
          {"number": 8, "title": "[Lab] W05 Q01", "user": {"login": "bharath"}, "created_at": "2026-11-02T12:30:00Z",
           "html_url": "https://github.com/owner/Java/issues/8", "labels": [{"name": "lab-submission"}, {"name": "lab-rejected"}]},
          {"number": 9, "title": "[Lab] W04 L07", "user": {"login": "anitha-r"}, "created_at": "2026-10-26T09:30:00Z",
           "html_url": "https://github.com/owner/Java/issues/9", "labels": [{"name": "lab-submission"}, {"name": "lab-accepted"}]}]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, obj=None, raw=None):
        body = raw if raw is not None else (json.dumps(obj).encode() if obj is not None else b"")
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path.split("/")              # ['', 'repos', owner, repo, ...]
        if self.headers.get("Authorization") != "Bearer test-token":
            return self.reply(401, {"message": "Bad credentials"})
        repo = "/".join(p[2:4])
        rest = p[4:]
        return repo, rest, urllib.parse.parse_qs(u.query)

    def do_GET(self):
        r = self.route()
        if r is None:
            return
        repo, rest, q = r
        files = Fake.files.get(repo)
        if files is None:
            return self.reply(404, {"message": "Not Found"})
        if rest[0] == "contents":
            path = urllib.parse.unquote("/".join(rest[1:]))
            return self.reply(200, raw=files[path].encode()) if path in files else self.reply(404, {"message": "Not Found"})
        if rest[:3] == ["git", "ref", "heads"]:
            return self.reply(200, {"object": {"sha": "c%d" % len(Fake.commits)}})
        if rest[:2] == ["git", "trees"]:
            return self.reply(200, {"tree": [{"path": k, "type": "blob"} for k in sorted(files)]})
        if rest[:2] == ["git", "commits"]:
            return self.reply(200, {"tree": {"sha": "t-" + rest[2]}})
        if rest[:2] == ["actions", "workflows"]:
            runs = [{"created_at": "2026-11-02T09:00:05Z", "status": "completed", "conclusion": "success",
                     "actor": {"login": "teacher"}, "html_url": "https://github.com/%s/actions/runs/1" % repo}]
            return self.reply(200, {"workflow_runs": runs})
        if rest[0] == "issues":
            return self.reply(200, ISSUES if q.get("page", ["1"])[0] == "1" else [])
        return self.reply(404, {"message": "Not Found"})

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_POST(self):
        r = self.route()
        if r is None:
            return
        repo, rest, _ = r
        b = self.body()
        if rest[:2] == ["actions", "workflows"] and rest[3] == "dispatches":
            Fake.dispatches.append((repo, rest[2], b))
            return self.reply(204)
        if rest[:2] == ["git", "trees"]:
            Fake.pending[repo] = {e["path"]: e["content"] for e in b["tree"]}
            return self.reply(201, {"sha": "tree-new"})
        if rest[:2] == ["git", "commits"]:
            return self.reply(201, {"sha": "commit-new"})
        return self.reply(404, {"message": "Not Found"})

    def do_PATCH(self):
        r = self.route()
        if r is None:
            return
        repo, rest, _ = r
        self.body()
        if rest[:3] == ["git", "refs", "heads"]:
            Fake.files[repo].update(Fake.pending.pop(repo, {}))
            Fake.commits.append(repo)
            return self.reply(200, {"object": {"sha": "commit-new"}})
        return self.reply(404, {"message": "Not Found"})


SERVER = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=SERVER.serve_forever, daemon=True).start()
os.environ["LAB_GITHUB_API"] = "http://127.0.0.1:%d" % SERVER.server_port
os.environ.setdefault("LAB_REPO", "invalid-owner-x/none")          # the student app reads nothing real

from streamlit.testing.v1 import AppTest  # noqa: E402

SECRETS = {"TEACHER_PASSWORD": "lab-pass", "GITHUB_TOKEN": "test-token", "LAB_REPO": LAB, "GRADEBOOK_REPO": BOOK}


def teacher():
    at = AppTest.from_file(os.path.join(APPS, "teacher", "app.py"), default_timeout=180)
    for k, v in SECRETS.items():
        at.secrets[k] = v
    at.run()
    at.text_input[0].set_value("lab-pass")
    at.button[0].click()
    at.run()
    return at


def by_label(widgets, label):
    return next(w for w in widgets if w.label == label)


class StudentApp(unittest.TestCase):
    def test_practice(self):
        at = AppTest.from_file(os.path.join(APPS, "student", "app.py"), default_timeout=180)
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertIn("No assessment is open now", at.info[0].value)
        by_label(at.text_input, "Register number").set_value("24bcl 0123")
        by_label(at.text_input, "Full name").set_value("Anitha  R")
        at.button[0].click()
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertIn("24BCL0123", " ".join(c.value for c in at.caption))
        q = by_label(at.selectbox, "Question")
        self.assertIn("E16", q.options[-4] + " ".join(q.options))
        q.set_value("E16")
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertTrue(any("in-memory database" in w.value for w in at.warning))

    def test_bad_regno(self):
        at = AppTest.from_file(os.path.join(APPS, "student", "app.py"), default_timeout=180)
        at.run()
        by_label(at.text_input, "Register number").set_value("12345")
        by_label(at.text_input, "Full name").set_value("Anitha R")
        at.button[0].click()
        at.run()
        self.assertTrue(any("Register number must look like" in e.value for e in at.error))


class TeacherApp(unittest.TestCase):
    def setUp(self):
        reset()

    def test_password_gate(self):
        at = AppTest.from_file(os.path.join(APPS, "teacher", "app.py"), default_timeout=60)
        for k, v in SECRETS.items():
            at.secrets[k] = v
        at.run()
        at.text_input[0].set_value("wrong")
        at.button[0].click()
        at.run()
        self.assertTrue(any("Wrong password" in e.value for e in at.error))
        self.assertEqual(len(at.tabs), 0)

    def test_sessions_open_close(self):
        at = teacher()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual(len(at.tabs), 6)
        df = at.dataframe[0].value
        self.assertEqual(list(df["session"]), ["W04", "W05"])
        self.assertEqual(list(df["state"]), ["closed", "OPEN"])
        by_label(at.text_input, "Session").set_value("W06")
        by_label(at.multiselect, "Questions").set_value(["Q01", "E05a"])
        by_label(at.number_input, "Close automatically after (minutes, 0 = when you close)").set_value(90)
        next(b for b in at.button if b.label == "Open session").click()
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual(Fake.dispatches[-1], (LAB, "lab-control.yml", {"ref": "main", "inputs": {
            "action": "open", "session": "W06", "questions": "Q01 E05a", "minutes": "90", "title": ""}}))
        next(b for b in at.button if b.label == "Close").click()
        at.run()
        self.assertEqual(Fake.dispatches[-1][2]["inputs"]["action"], "close")
        self.assertEqual(Fake.dispatches[-1][2]["inputs"]["session"], "W05")

    def test_submissions_marks_replay(self):
        at = teacher()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        metrics = {m.label: m.value for m in at.metric}
        self.assertEqual(metrics["Issues"], "2")
        self.assertEqual(metrics["Accepted"], "1")
        self.assertEqual(metrics["Rejected"], "1")
        frames = [d.value for d in at.dataframe]
        self.assertTrue(any("average_percent" in list(f.columns) for f in frames))
        self.assertTrue(any("Flags" in w.value and "1 paste attempt(s) blocked" in w.value for w in at.warning))
        self.assertTrue(any("class Main {}" in c.value for c in at.code))
        next(b for b in at.button if b.label == "Collect and mark now").click()
        at.run()
        self.assertEqual(Fake.dispatches[-1], (BOOK, "collect.yml", {"ref": "main", "inputs": {"session": "W05"}}))

    def test_new_question_and_key(self):
        at = teacher()
        by_label(at.text_input, "Question id").set_value("Q09")
        by_label(at.text_area, "Statement (Markdown, first line '# Q04 Title')").set_value("# Q09 Square\n\nRead n, print n*n.\n")
        by_label(at.text_area, "Reference solution (Main.java)").set_value(
            "import java.util.*;\npublic class Main { public static void main(String[] a) { Scanner s = new Scanner(System.in);"
            " long n = s.nextLong(); System.out.println(n * n); } }\n")
        by_label(at.text_area, "Sample inputs shown to students: one case per block, blocks separated by a line ---").set_value("3\n---\n4\n")
        by_label(at.text_area, "Hidden marking inputs (same format; boundaries, invalid and large values)").set_value("0\n---\n100000\n")
        next(b for b in at.button if b.label == "Run the solution on every case").click()
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        next(b for b in at.button if b.label.startswith("1. Save solution")).click()
        at.run()
        book = Fake.files[BOOK]
        self.assertEqual(book["tests/Q09/expected-1.txt"], "9\n")
        self.assertEqual(book["tests/Q09/expected-4.txt"], "10000000000\n")
        self.assertIn("public class Main", book["solutions/Q09/Main.java"])
        next(b for b in at.button if b.label.startswith("2. Publish statement")).click()
        at.run()
        lab = Fake.files[LAB]
        self.assertEqual(lab["lab/questions/Q09/expected-2.txt"], "16\n")
        self.assertNotIn("lab/questions/Q09/expected-3.txt", lab)          # hidden cases stay private
        next(b for b in at.button if b.label == "Create a new key pair").click()
        at.run()
        at.checkbox[0].check()
        at.run()
        next(b for b in at.button if b.label == "3. Publish the public key").click()
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertIn("BEGIN PUBLIC KEY", Fake.files[LAB]["lab/teacher-public-key.pem"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
