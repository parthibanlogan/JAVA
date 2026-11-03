# Streamlit apps of the Java Lab

| Folder | Entry file | Purpose |
|--------|-----------|---------|
| `student/` | `apps/student/app.py` | typed-only Java Lab on the real JDK 21; encrypted submission through a GitHub issue |
| `teacher/` | `apps/teacher/app.py` | sessions, submissions, marking, replay, questions with hidden cases, key pair |
| `labcore/` | | shared: Java 21 download (`jdk.py`), sandbox (`sandbox.py`, `sandbox.policy`, `LabJavac.java`, `mysql-shim/`), lab data (`labdata.py`), GitHub client (`github.py`) |
| `tests/` | | `python3 -m unittest discover -s apps/tests -v` |

Deployment and daily use: [docs/11-streamlit-apps.md](../docs/11-streamlit-apps.md).
