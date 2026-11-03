"""Compiles and runs student Java programs for the student app, on the real JDK 21.

Safety, in layers (Streamlit Community Cloud has no containers):
  * the app holds no secret: a program that escapes finds nothing worth taking;
  * javac runs in one warm server process that never executes student code (LabJavac.java);
  * every program runs in its own JVM under the Java 21 Security Manager with sandbox.policy:
    no files outside its fresh working folder, no network, no processes, no reflection on
    private members, no environment variables (except the three of Experiment 16);
  * operating-system limits: CPU seconds, address space (bounds heap and threads), file size,
    no core dumps, a wall-clock timeout that kills the whole process group, capped output;
  * at most SLOTS programs run at the same time; the others wait their turn.

Behaviour matches the gradebook (lab-system/grader): same main-class rule, same output
normalisation, Locale en_US, UTF-8, 1 MB file limit, 10 s time limit.
"""
import base64
import hashlib
import os
import queue
import re
import resource
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass, field

from . import ROOT
from .jdk import cache_dir, ensure_jdk

HERE = os.path.dirname(os.path.abspath(__file__))
POLICY = os.path.join(HERE, "sandbox.policy")
H2 = ("2.4.240", "29b70e427cc1c40cdc376283adbb0cc62853073797bb5fe5761f81fe73d57ce0",
      "https://github.com/h2database/h2database/releases/download/version-2.4.240/h2-2.4.240.jar")
TIME_LIMIT = 10.0          # seconds of wall-clock time per run (gradebook: 10)
CPU_LIMIT = 10             # seconds of CPU time per run
MAX_STDOUT = 64 * 1024     # kept like the gradebook
MAX_STDERR = 16 * 1024
MAX_SOURCE = 100_000       # characters of source code accepted
SLOTS = max(2, min(4, os.cpu_count() or 2))
AS_LIMIT = 2048 << 20      # address space: bounds heap, metaspace and the number of threads (about 128)
FSIZE_LIMIT = 1 << 20      # no file the program writes may exceed 1 MB (gradebook: ulimit -f 1024)
PRLIMIT = shutil.which("prlimit")
SM_WARNING = re.compile(r"^WARNING: (A command line option has enabled the Security Manager|"
                        r"The Security Manager is deprecated and will be removed in a future release)\s*$")
CLASS_NAME = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]{0,63}\.java$")


def normalise(text):
    """Same comparison as the gradebook and the website: line endings, trailing spaces, outer blank lines."""
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).strip()


def file_name_for(code):
    """File name javac needs: the public class, else Main.java (same as java-runner.js)."""
    m = re.search(r"public\s+(?:final\s+|abstract\s+)*class\s+(\w+)", code)
    return (m.group(1) if m else "Main") + ".java"


def main_class(files):
    """Class to run, by the gradebook's rule (lab-system/grader/grade.py)."""
    names = [os.path.splitext(n)[0] for n in files]
    if "Main" in names:
        return "Main"
    for text in files.values():
        if re.search(r"static\s+void\s+main\s*\(", text):
            m = re.search(r"public\s+(?:final\s+|abstract\s+)*class\s+(\w+)", text) or re.search(r"class\s+(\w+)", text)
            if m:
                return m.group(1)
    return "Main"


@dataclass
class Diagnostic:
    kind: str
    file: str
    line: int
    column: int
    message: str


@dataclass
class Compiled:
    ok: bool
    diagnostics: list
    main: str
    workdir: str
    ms: int
    files: dict = field(default_factory=dict)

    def text(self):
        """Diagnostics in javac's familiar form, with the source line and a caret."""
        out = []
        for d in self.diagnostics:
            head = "%s:%d: %s: %s" % (d.file or "?", d.line, d.kind.lower().replace("mandatory_", ""), d.message) \
                if d.line else "%s: %s" % (d.kind.lower(), d.message)
            out.append(head)
            src = self.files.get(d.file, "")
            lines = src.split("\n")
            if d.line and 0 < d.line <= len(lines):
                out.append(lines[d.line - 1].rstrip())
                out.append(" " * max(0, d.column - 1) + "^")
        return "\n".join(out)

    def cleanup(self):
        shutil.rmtree(self.workdir, ignore_errors=True)


@dataclass
class RunResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    output_limited: bool
    ms: int
    files: dict = field(default_factory=dict)   # small text files the program wrote

    @property
    def outcome(self):
        """The activity-log outcome used by lab.html: ok | exception | timeout."""
        if self.timed_out:
            return "timeout"
        return "exception" if self.exit_code != 0 else "ok"


class Toolchain:
    """One per app process (st.cache_resource): JDK, libraries, compile server, run slots."""

    def __init__(self, log=lambda msg: None):
        self.log = log
        self.java_home = ensure_jdk(log)
        self.java = os.path.join(self.java_home, "bin", "java")
        self.base = os.path.join(cache_dir(), "sandbox")
        self.runs = os.path.join(self.base, "runs")
        self.lib = os.path.join(self.base, "lib")
        os.makedirs(self.runs, exist_ok=True)
        os.makedirs(self.lib, exist_ok=True)
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(SLOTS)
        self._server = None
        self._lines = None
        self._jdbc_cp = self._prepare_jdbc()
        self._start_server()

    # ------------------------------------------------------------------ libraries
    def _prepare_jdbc(self):
        """H2 (downloaded, checksum verified) and the jdbc:mysql shim; None when unavailable."""
        version, sha, url = H2
        h2 = os.path.join(self.lib, "h2-%s.jar" % version)
        try:
            if not os.path.exists(h2):
                req = urllib.request.Request(url, headers={"User-Agent": "java-lab-streamlit"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = r.read()
                if hashlib.sha256(data).hexdigest() != sha:
                    raise OSError("H2 checksum mismatch")
                with open(h2 + ".part", "wb") as f:
                    f.write(data)
                os.replace(h2 + ".part", h2)
            shim = os.path.join(self.lib, "lab-mysql.jar")
            if not os.path.exists(shim):
                build = tempfile.mkdtemp(dir=self.base)
                src = os.path.join(HERE, "mysql-shim")
                rc = subprocess.run([os.path.join(self.java_home, "bin", "javac"), "-Xlint:none", "-nowarn", "-cp", h2,
                                     "-d", build, os.path.join(src, "lab", "mysql", "Driver.java")],
                                    capture_output=True, text=True, timeout=120)
                if rc.returncode != 0:
                    raise OSError("shim does not compile: " + rc.stderr[-500:])
                shutil.copytree(os.path.join(src, "META-INF"), os.path.join(build, "META-INF"))
                subprocess.run([os.path.join(self.java_home, "bin", "jar"), "cf", shim + ".part", "-C", build, "."],
                               check=True, capture_output=True, timeout=120)
                os.replace(shim + ".part", shim)
                shutil.rmtree(build, ignore_errors=True)
            return os.pathsep.join([shim, h2])
        except (OSError, subprocess.SubprocessError) as e:
            self.log("JDBC support unavailable: %s" % e)
            return None

    @property
    def jdbc_available(self):
        return self._jdbc_cp is not None

    # ------------------------------------------------------------------ compile server
    def _start_server(self):
        classes = os.path.join(self.base, "server")
        os.makedirs(classes, exist_ok=True)
        if not os.path.exists(os.path.join(classes, "LabJavac.class")) or \
                os.path.getmtime(os.path.join(classes, "LabJavac.class")) < os.path.getmtime(os.path.join(HERE, "LabJavac.java")):
            subprocess.run([os.path.join(self.java_home, "bin", "javac"), "-d", classes, os.path.join(HERE, "LabJavac.java")],
                           check=True, capture_output=True, timeout=120)
        self._server = subprocess.Popen(
            [self.java, "-Xmx256m", "-XX:+UseSerialGC", "-XX:-UsePerfData", "-Xshare:auto", "-cp", classes, "LabJavac"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=self._env(),
            text=True, encoding="utf-8", bufsize=1)
        self._lines = queue.Queue()
        server, lines = self._server, self._lines

        def pump():
            for line in server.stdout:
                lines.put(line.rstrip("\n"))
            lines.put(None)
        threading.Thread(target=pump, daemon=True).start()
        first = self._lines.get(timeout=120)
        if first != "READY":
            raise RuntimeError("compile server did not start")

    def _restart_server(self):
        try:
            self._server.kill()
        except OSError:
            pass
        self._start_server()

    def _request(self, src, out, timeout=30.0):
        rid = uuid.uuid4().hex[:12]
        self._server.stdin.write("%s\t%s\t%s\n" % (rid, src, out))
        self._server.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            line = self._lines.get(timeout=max(0.1, deadline - time.monotonic()))
            if line is None:
                raise RuntimeError("compile server stopped")
            head = line.split("\t")
            if len(head) == 3 and head[0] == rid:
                break
        diags = []
        for _ in range(int(head[2])):
            kind, ln, col, msg = self._lines.get(timeout=max(0.1, deadline - time.monotonic())).split("\t")
            name, _, text = base64.b64decode(msg).decode("utf-8").partition("\x00")
            diags.append(Diagnostic(kind, name, int(ln), int(col), text))
        return head[1] == "1", diags

    @staticmethod
    def _env():
        env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        return env

    def compile(self, files):
        """files: {"Main.java": source}. Returns Compiled (call .cleanup() when done)."""
        work = tempfile.mkdtemp(prefix="c-", dir=self.runs)
        src, classes = os.path.join(work, "src"), os.path.join(work, "classes")
        os.makedirs(src)
        os.makedirs(classes)
        clean = {}
        for name, text in files.items():
            if not CLASS_NAME.match(name):
                raise ValueError("invalid file name %r" % name)
            if len(text) > MAX_SOURCE:
                shutil.rmtree(work, ignore_errors=True)
                return Compiled(False, [Diagnostic("ERROR", name, 0, 0, "the program is longer than %d characters" % MAX_SOURCE)],
                                "Main", work, 0, files)
            clean[name] = text
            with open(os.path.join(src, name), "w", encoding="utf-8") as f:
                f.write(text)
        t0 = time.monotonic()
        with self._lock:
            try:
                ok, diags = self._request(src, classes)
            except (queue.Empty, RuntimeError, OSError, ValueError) as e:
                self._restart_server()
                ok, diags = False, [Diagnostic("ERROR", "", 0, 0, "the compiler did not answer (%s); press Run again" % type(e).__name__)]
        return Compiled(ok, diags, main_class(clean), work, int((time.monotonic() - t0) * 1000), clean)

    # ------------------------------------------------------------------ running
    def run(self, compiled, stdin_text="", time_limit=TIME_LIMIT, setup_sql=None, wait=60.0):
        """Runs compiled.main once in a fresh folder. Raises TimeoutError when no slot is free in `wait` s."""
        if not self._slots.acquire(timeout=wait):
            raise TimeoutError("the server is busy; press Run again in a few seconds")
        work = tempfile.mkdtemp(prefix="r-", dir=self.runs)
        try:
            return self._run(compiled, stdin_text, time_limit, setup_sql, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
            self._slots.release()

    def _run(self, compiled, stdin_text, time_limit, setup_sql, work):
        cp = os.path.join(compiled.workdir, "classes")
        args = [self.java,
                "-Djava.security.manager", "-Djava.security.policy==" + POLICY,
                "-Dlab.work=" + work, "-Dlab.lib=" + self.lib, "-Djava.io.tmpdir=" + work,
                "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8",
                "-Duser.language=en", "-Duser.country=US",
                "-Xmx128m", "-Xss8m", "-XX:TieredStopAtLevel=1", "-XX:+UseSerialGC", "-XX:ReservedCodeCacheSize=32m",
                "-XX:MaxMetaspaceSize=64m", "-XX:CompressedClassSpaceSize=32m", "-XX:-UsePerfData",
                "-XX:ErrorFile=/dev/null", "-Xshare:auto"]
        if self._jdbc_cp:
            cp += os.pathsep + self._jdbc_cp
            if setup_sql:
                args.append("-Dlab.mysql.setup=" + setup_sql)
        args += ["-cp", cp, compiled.main]
        # Limits are set by util-linux prlimit before java starts (a Python preexec_fn is not safe in
        # Streamlit's threaded server); the fallback is used only where prlimit is missing.
        preexec = None
        if PRLIMIT:
            args = [PRLIMIT, "--cpu=%d:%d" % (CPU_LIMIT, CPU_LIMIT + 1), "--as=%d" % AS_LIMIT, "--fsize=%d" % FSIZE_LIMIT,
                    "--core=0", "--nofile=256", "--"] + args
        else:
            def preexec():
                resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT, CPU_LIMIT + 1))
                resource.setrlimit(resource.RLIMIT_AS, (AS_LIMIT, AS_LIMIT))
                resource.setrlimit(resource.RLIMIT_FSIZE, (FSIZE_LIMIT, FSIZE_LIMIT))
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
                resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))

        t0 = time.monotonic()
        proc = subprocess.Popen(args, cwd=work, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=self._env(), start_new_session=True, preexec_fn=preexec)
        out, err, limited = bytearray(), bytearray(), threading.Event()

        def reader(stream, buf, cap):
            while True:
                chunk = stream.read1(8192) if hasattr(stream, "read1") else stream.read(8192)
                if not chunk:
                    return
                room = cap - len(buf)
                if room > 0:
                    buf.extend(chunk[:room])
                if len(chunk) > room:
                    limited.set()
                    _kill(proc)
                    return

        threads = [threading.Thread(target=reader, args=(proc.stdout, out, MAX_STDOUT), daemon=True),
                   threading.Thread(target=reader, args=(proc.stderr, err, MAX_STDERR), daemon=True)]
        for t in threads:
            t.start()
        try:
            proc.stdin.write(stdin_text.encode("utf-8"))
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        timed_out = False
        try:
            proc.wait(timeout=time_limit)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill(proc)
            proc.wait()
        for t in threads:
            t.join(timeout=2)
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except OSError:
                pass
        ms = int((time.monotonic() - t0) * 1000)
        code = proc.returncode
        if code in (-signal.SIGXCPU, -signal.SIGKILL) and not limited.is_set():
            timed_out = True
        stderr = "\n".join(l for l in err.decode("utf-8", "replace").split("\n") if not SM_WARNING.match(l))
        written = {}
        for name in sorted(os.listdir(work))[:10]:
            p = os.path.join(work, name)
            if os.path.isfile(p) and os.path.getsize(p) <= 4096:
                with open(p, "rb") as f:
                    data = f.read()
                try:
                    written[name] = data.decode("utf-8")
                except UnicodeDecodeError:
                    written[name] = "(binary file, %d bytes)" % len(data)
        return RunResult(out.decode("utf-8", "replace"), stderr.strip("\n"), code if code is not None else -1,
                         timed_out, limited.is_set(), ms, written)


def _kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def setup_sql_for(qdir):
    """setup.sql of a question folder (Experiment 16), if present."""
    p = os.path.join(qdir, "setup.sql") if qdir else None
    return p if p and os.path.isfile(p) else None


__all__ = ["Toolchain", "Compiled", "RunResult", "normalise", "file_name_for", "main_class", "setup_sql_for", "ROOT"]
