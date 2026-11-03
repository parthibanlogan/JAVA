# 11. Java Lab on Streamlit: student app and teacher app

Two free apps on Streamlit Community Cloud, deployed from this repository. They work together with
everything in guide 10 (session control, intake robot, private gradebook); nothing there changes.

| App | Entry file | Who | What |
|-----|-----------|-----|------|
| **Student app** | `apps/student/app.py` | students, public | type (paste and drop blocked and logged), **Run** and **Check** on the real JDK 21 on the server, **Submit**: encrypted package, then a GitHub issue as on `lab.html`. Every course program runs, including files (Exp. 8-10), serialization (11-12) and JDBC (16, on an in-memory database in MySQL mode) |
| **Teacher app** | `apps/teacher/app.py` | you, private | **Sessions** open and close; **Submissions** live counts; **Marks** start the gradebook and read marks, flags and similar pairs; **Replay** how each program was typed; **Questions** new questions with hidden cases (expected outputs made on Java 21); **Keys** create and publish the key pair |

Design rules that keep it safe on a shared free server:

* The student app holds **no secret**. It runs student programs, so it must have nothing worth taking: it
  encrypts with your **public** key only, and students still submit through a GitHub issue (GitHub's clock
  decides acceptance; every student needs a free GitHub account, as for `lab.html`).
* The teacher app holds your token and password and **never runs student code**.
* Student programs run one per Java process under the Java 21 Security Manager (no files outside their own
  fresh folder, no network, no processes, no environment variables, no private reflection), with limits of
  10 s, 128 MB heap, about 128 threads, 1 MB per file, 64 KB of output; at most 4 run at the same time, the
  others wait a moment. These are the gradebook's rules, so Check predicts the marks.

---

## Part A. One-time set-up on a new GitHub account (about 60 minutes)

Every step ends with a check. Do not continue until it passes. `YOU` is your GitHub username.

### A1. Account
1. github.com, **Sign up**; open the confirmation e-mail and confirm your address.
2. If GitHub asks for two-factor authentication, set it up (an authenticator app); it is required for
   accounts that push code.

**Check:** your picture (top right), **Settings, Emails**: the address is shown without *Unverified*.

### A2. The two repositories
1. **+** (top right), **New repository**: name `Java`, **Public**, switch on **Add README**, **Create repository**.
2. **+**, **New repository**: name `java-lab-gradebook`, **Private**, nothing added (no README), **Create repository**.

**Check:** `https://github.com/YOU/Java` shows README.md; `https://github.com/YOU/java-lab-gradebook` shows
*Quick setup* (empty) and the label *Private*.

### A3. Website switched on
`YOU/Java`, **Settings, Pages, Build and deployment, Source: GitHub Actions**.

**Check:** the Source box shows *GitHub Actions*.

### A4. Setup token (used once, deleted in A12)
Your picture, **Settings, Developer settings, Personal access tokens, Fine-grained tokens, Generate new token**:

| Field | Value |
|-------|-------|
| Token name | `java-lab-setup` |
| Expiration | 7 days |
| Repository access | **Only select repositories**: `Java`, `java-lab-gradebook` |
| Repository permissions | **Contents**: Read and write; **Workflows**: Read and write; **Secrets**: Read and write |

**Generate token**; copy it into a temporary note (it starts with `github_pat_` and is shown once).

**Check:** the token list shows `java-lab-setup` with the expiry date.

### A5. Put the platform into the repositories (one command)
1. `YOU/Java`, green **Code** button, tab **Codespaces**, **Create codespace on main**; wait until the editor opens.
2. Drag `Java-main-streamlit.zip` from your computer into the file list on the left (it appears there).
3. Terminal (menu, **Terminal, New Terminal**):

```bash
unzip -q Java-main-streamlit.zip && bash Java-main/tools/setup_new_account.sh
```

4. When asked, paste the setup token (nothing is shown) and press Enter.

The script copies the platform in, points every address to `YOU/Java`, checks it (projects, problem bank,
lab system tests, course programs when Java 21 is present), creates the key pair, pushes `YOU/Java`, builds and
pushes the gradebook, and stores the private key as the gradebook secret `LAB_PRIVATE_KEY`.

**Check:** the last lines show *Done*, your three addresses and the **key id** (16 characters); no line starts
with *STOPPED*. `https://github.com/YOU/java-lab-gradebook` now shows `README.md`, `roster.csv`, `solutions`,
`tests`; its **Settings, Secrets and variables, Actions** lists `LAB_PRIVATE_KEY`.

### A6. Keep the private key, then clean up
1. In the Codespace file list, right-click `lab-private-key.pem`, **Download**; keep it in a password manager or
   an encrypted drive. Without it no submission can be read, and nobody can recreate it.
2. Terminal: `rm lab-private-key.pem`
3. github.com/codespaces: the codespace, **...**, **Delete** (it is not needed any more).

**Check:** the downloaded file starts with `-----BEGIN PRIVATE KEY-----`.

### A7. Website and checks on GitHub (15-25 minutes the first time)
`YOU/Java`, tab **Actions**: wait until **CI** and **Deploy website to GitHub Pages** are green (the in-browser
Java compiler is built from source on the first run; later runs reuse it).

**Check:** `https://YOU.github.io/Java/` opens (YOU in lower case); `.../lab.html`, Practice, **Start**: the
right-hand box says *Java compiler ready*, and a Run of the example program prints its output.

### A8. Token for the teacher app
**Generate new token** again (fine-grained):

| Field | Value |
|-------|-------|
| Token name | `java-lab-teacher-app` |
| Expiration | the end of the semester |
| Repository access | **Only select repositories**: `Java`, `java-lab-gradebook` |
| Repository permissions | **Actions**: Read and write; **Contents**: Read and write; **Issues**: Read-only |

Copy it (`github_pat_...`). It has no Workflows or Secrets permission on purpose.

### A9. The two Streamlit apps
Open `https://share.streamlit.io`, **Continue with GitHub**, allow access.

**Student app:** **Create app**, *Deploy a public app from GitHub*: repository `YOU/Java`, branch `main`, main file
path `apps/student/app.py`, App URL for example `YOU-java-lab`, **Advanced settings**, Python `3.12`, **Deploy**.
No secrets.

**Check:** after 1-2 minutes the page *Java Lab* says *No assessment is open now*; register number
`24BCL0001`, a name, **Start**, question `L01`, type a short program, **Run**: its output appears.

**Teacher app:** **Create app** again: main file path `apps/teacher/app.py`, App URL for example
`YOU-java-lab-teacher`, Python `3.12`, **Advanced settings, Secrets**:

```toml
TEACHER_PASSWORD = "a long password only you know"
GITHUB_TOKEN = "github_pat_... (the token of A8)"
LAB_REPO = "YOU/Java"
GRADEBOOK_REPO = "YOU/java-lab-gradebook"
```

**Deploy**. Then **Share** (top right), *Only specific people can view this app*, add your e-mail (one private
app is allowed; this is the one).

**Check:** sign in with the password; tab **Keys** shows the same **key id** as A5; tab **Sessions** shows
*No sessions yet* and no red error.

### A10. Optional
* `lab.html` links to the student app: in `site/assets/js/common.js` set
  `studentApp: 'https://YOU-java-lab.streamlit.app'` (edit on GitHub with the pencil icon, **Commit changes**).
* For 41-80 students at the same time, request more resources for educational apps:
  `https://info.snowflake.com/streamlit-resource-increase-request.html`.
* `roster.csv` in the gradebook: one line per student, `regno,name,github`.

### A11. The whole chain once (15 minutes)
1. Teacher app, **Sessions, Open**: session `T00`, question `Q01`, 20 minutes. **Check:** the table shows `T00 OPEN`
   within a minute (**Refresh**).
2. Student app in a private window: `24BCL0001`, a name, **Start**, assessment **T00**, question **Q01**; type the
   program (statement on the left), **Check**: *2 of 2*; **Submit**, **OK**; copy the package (icon at the top right
   of the box), **Open GitHub**, click in **Package**, paste, **Create**. **Check:** within a minute the issue gets
   the reply **Accepted** with the same receipt.
3. Teacher app, **Sessions, Close**; **Submissions**: *Accepted 1*. **Marks, Collect and mark now**; after 3-6
   minutes **Refresh**: `24BCL0001` with `Q01` 6/6. **Replay**: the typing.
4. On the test issue, add the label `lab-ignore` (so it never counts).

### A12. Delete the setup token
**Settings, Developer settings, Personal access tokens, Fine-grained tokens**, `java-lab-setup`, **Delete**.

### The account that already holds the original repository
If your repository already contains the earlier version of this platform (history up to "Merge pull request #1"),
do A2 only for `java-lab-gradebook`, then A3 and A4, and replace A5 by: in a Codespace of the repository drag in
`java-lab-streamlit.patch` (replace the file if an older copy is there), then

```bash
git am java-lab-streamlit.patch && git rm -qf java-lab-streamlit.patch && git commit -qm "Remove the patch file" && bash tools/setup_new_account.sh
```

Uploading the patch file on the GitHub website does not apply it: it only stores the file.

---

## Part B. Every lab session

| When | Teacher app | Students (student app) |
|------|-------------|------------------------|
| 10 min before | open the **student app** once (it sleeps after 12 h without visitors; the first visit wakes it, 1-2 min) | |
| Start | **Sessions, Open**: session (`W05`, or `W05-A` per batch), questions, minutes (0 = until you close), title | sidebar: register number, full name, **Start**; choose the session and question |
| During | **Submissions**: accepted and rejected as they come | type, **Run** (keyboard input in the box), **Check**, **Submit**, copy, **Open GitHub**, paste, **Create**; submit again to improve: the last accepted one counts |
| End | **Sessions, Close** | |
| After | **Marks, Collect and mark now**; read *Marks per student*, flags, *Similar programs*; download the CSVs; **Replay** flagged students | |

Shared lab PCs: students press **Remove my work from this computer** in the sidebar before leaving. Work is
saved in the browser after every keystroke; a reload restores it.

---

## Part C. A new question with hidden cases (Questions tab)

1. Question id (`Q07`), statement in Markdown (first line `# Q07 Title`; state the exact input order and
   output format), your solution (`Main.java`), sample inputs (shown to students) and hidden inputs
   (boundaries, invalid and large values), cases separated by a line `---`.
2. **Run the solution on every case**: the app runs it on Java 21 and shows every output.
3. **Save solution and marking cases in the gradebook** (`solutions/Q07`, `tests/Q07`: samples first, then hidden).
4. **Publish statement and samples to students** (`lab/questions/Q07`) shortly before the lab if the question
   should stay unseen: the public repository can be read by anyone.

Course programs (`L01`-`L14`, `E01a`-`E16`) need nothing: their cases are already in the gradebook template.

---

## Part D. Limits (stated plainly)

* **Free hosting.** Community Cloud's limits are shared and may change; the app queues programs so that a burst
  of Run presses does not fail, but at the minimum CPU share answers can take several seconds. Apply for more
  resources (A6) and keep the website's `lab.html` as the fallback: both produce the same packages.
* **Security Manager.** It is deprecated by the Java project and permanently disabled from Java 24 (JEP 486); the
  app pins Java 21, where it works. It is one layer: the app holds no secret, runs each program in its own process with operating
  system limits, and keeps no student work on the server.
* **Paste blocking** is a deterrent, not a lock (guide 10, Part H). Packages from the student app also carry
  the server's own log of every Run, Check and Submit (time, code fingerprint, outcome), visible in Replay.
* **Experiment 16** runs against H2 in MySQL mode, created by `setup.sql` for every run; SQL that only MySQL
  accepts may behave differently. CI keeps checking the program against a real MySQL 8.4 server.

---

## Part E. Troubleshooting

| Symptom | Fix |
|---------|-----|
| Script: *STOPPED: push to YOU/Java refused* | the setup token (A4) lacks `Java`, or Contents or Workflows read/write: make a new one, run the command again |
| Script: *STOPPED: gradebook not pushed* | `java-lab-gradebook` does not exist (A2) or is not in the token; fix, run again (finished steps are kept) |
| Script: *STOPPED: secret not stored* | the token lacks Secrets read/write on the gradebook; or add it by hand: gradebook, **Settings, Secrets and variables, Actions, New repository secret** `LAB_PRIVATE_KEY` = whole content of `lab-private-key.pem` |
| Pages run fails with *Get Pages site failed* | A3 was skipped: set Source to GitHub Actions, then **Re-run all jobs** |
| Student app shows *Zzzz, this app has gone to sleep* | press the button on that page (anyone can); open it before the lab |
| *Java could not be prepared on the server* | **Manage app** (bottom right, signed in), **Reboot app**; the download is retried |
| *the server is busy; press Run again* | many runs at once: press again after a few seconds; apply for more resources (A6) |
| Submit disabled: *The teacher has not published the submission key yet* | Part A5 |
| Banner says no assessment open although you opened one | wait up to 20 s and reload; check **Sessions, Lab session control runs** is green |
| Teacher app: *GitHub 401* or *403* | the token expired or lacks a permission (A3); paste a new one in the app's Secrets |
| Teacher app: *GitHub 404* for the gradebook | `GRADEBOOK_REPO` in the Secrets, and the token includes that repository |
| *This app has gone over its resource limits* | **Reboot app**; apply for more resources |

---

## Part F. Running and testing on a PC or in a Codespace

```bash
pip install -r apps/student/requirements.txt
```

```bash
streamlit run apps/student/app.py
```

```bash
python3 -m unittest discover -s apps/tests -v
```

The tests compile and run every course program in the sandbox and compare with the expected outputs, try
hostile programs (files, environment, processes, network, reflection, endless loops, floods, thread and memory
bombs), and drive both apps headless against a simulated GitHub. The teacher app locally reads
`TEACHER_PASSWORD`, `GITHUB_TOKEN`, `LAB_REPO` and `GRADEBOOK_REPO` from the environment or from
`.streamlit/secrets.toml` (ignored by git).
