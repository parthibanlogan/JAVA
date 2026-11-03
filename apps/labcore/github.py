"""Minimal GitHub REST client for the teacher app (standard library only).

Token: a fine-grained personal access token limited to the two lab repositories, with
  public lab repository : Actions read/write, Contents read/write, Issues read, Metadata read
  private gradebook     : Actions read/write, Contents read/write, Metadata read
"""
import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("LAB_GITHUB_API", "https://api.github.com")   # override only for tests


class GitHubError(RuntimeError):
    def __init__(self, status, message):
        super().__init__("GitHub %s: %s" % (status, message))
        self.status = status


class GitHub:
    def __init__(self, token):
        self.token = token

    def request(self, method, path, body=None, accept="application/vnd.github+json", raw=False):
        url = path if path.startswith("https://") else API + path
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "java-lab-teacher"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = r.read()
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode()).get("message", "")
            except (ValueError, UnicodeDecodeError):
                msg = e.reason
            raise GitHubError(e.code, msg) from None
        except urllib.error.URLError as e:
            raise GitHubError(0, str(e.reason)) from None
        if raw:
            return payload
        return json.loads(payload) if payload else None

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def paged(self, path, limit=1000):
        out, page = [], 1
        sep = "&" if "?" in path else "?"
        while len(out) < limit:
            items = self.get("%s%sper_page=100&page=%d" % (path, sep, page))
            if isinstance(items, dict):        # search results
                items = items.get("items", [])
            out.extend(items)
            if len(items) < 100:
                break
            page += 1
        return out[:limit]

    # ------------------------------------------------------------------ repositories
    def repo(self, repo):
        return self.get("/repos/%s" % repo)

    def file_text(self, repo, path, ref="main"):
        """Text of a file, or None when it does not exist."""
        try:
            data = self.get("/repos/%s/contents/%s?ref=%s" % (repo, urllib.parse.quote(path), ref), accept="application/vnd.github.raw+json", raw=True)
        except GitHubError as e:
            if e.status == 404:
                return None
            raise
        return data.decode("utf-8", "replace")

    def tree(self, repo, ref="main"):
        """Every file path of the branch (recursive tree)."""
        sha = self.get("/repos/%s/git/ref/heads/%s" % (repo, ref))["object"]["sha"]
        t = self.get("/repos/%s/git/trees/%s?recursive=1" % (repo, sha))
        return [x["path"] for x in t.get("tree", []) if x.get("type") == "blob"]

    def commit_files(self, repo, files, message, ref="main", attempts=4):
        """One commit with all files ({path: text}); retried when the branch moved meanwhile."""
        for attempt in range(attempts):
            head = self.get("/repos/%s/git/ref/heads/%s" % (repo, ref))["object"]["sha"]
            base_tree = self.get("/repos/%s/git/commits/%s" % (repo, head))["tree"]["sha"]
            entries = [{"path": p, "mode": "100644", "type": "blob", "content": t} for p, t in sorted(files.items())]
            tree = self.request("POST", "/repos/%s/git/trees" % repo, {"base_tree": base_tree, "tree": entries})["sha"]
            commit = self.request("POST", "/repos/%s/git/commits" % repo, {"message": message, "tree": tree, "parents": [head]})["sha"]
            try:
                self.request("PATCH", "/repos/%s/git/refs/heads/%s" % (repo, ref), {"sha": commit, "force": False})
                return commit
            except GitHubError as e:
                if e.status != 422 or attempt == attempts - 1:
                    raise
                time.sleep(1 + attempt)
        return None

    # ------------------------------------------------------------------ workflows
    def dispatch(self, repo, workflow, inputs, ref="main"):
        self.request("POST", "/repos/%s/actions/workflows/%s/dispatches" % (repo, workflow), {"ref": ref, "inputs": inputs})

    def runs(self, repo, workflow, n=5):
        return self.get("/repos/%s/actions/workflows/%s/runs?per_page=%d" % (repo, workflow, n)).get("workflow_runs", [])

    # ------------------------------------------------------------------ issues
    def issues(self, repo, label, since=None, limit=1000):
        q = "/repos/%s/issues?state=all&labels=%s&sort=created&direction=desc" % (repo, urllib.parse.quote(label))
        if since:
            q += "&since=" + since
        return [i for i in self.paged(q, limit) if "pull_request" not in i]


def b64(text):
    return base64.b64encode(text.encode()).decode()
