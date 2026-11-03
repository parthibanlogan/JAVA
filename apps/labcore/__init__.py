"""Shared code of the two Streamlit apps of the Java Lab (apps/student, apps/teacher).

The apps run on Streamlit Community Cloud from this repository; their working directory is the
repository root, so the lab tools (tools/lab) and course files (course/, lab/) are imported and
read from the same checkout as the website.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(ROOT, "tools", "lab"), os.path.join(ROOT, "lab-system", "grader")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
