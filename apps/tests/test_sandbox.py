"""Tests of the student app's Java sandbox (apps/labcore/sandbox.py) on the real JDK 21.

    python3 -m unittest discover -s apps/tests -v
1. Every course program (lessons, experiments incl. 16 on the H2 shim) compiles and reproduces each
   expected output, exactly as tools/CourseCheck.java does on the plain JDK.
2. Hostile programs are contained: files outside the run folder, environment, processes,
   network, reflection, endless loops, output floods, thread and memory bombs.
3. Compile errors come back with line numbers; the main-class rule matches the gradebook.
"""
import os
import sys
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from labcore import ROOT, sandbox  # noqa: E402

TC = None


def toolchain():
    global TC
    if TC is None:
        TC = sandbox.Toolchain(print)
    return TC


def course_programs():
    out = []
    for group in ("lessons", "experiments"):
        base = os.path.join(ROOT, "course", group)
        for d in sorted(os.listdir(base)):
            if os.path.exists(os.path.join(base, d, "meta.properties")):
                out.append(os.path.join(base, d))
    return out


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def cases(d):
    n, res = 1, []
    while True:
        suf = "" if n == 1 else "-%d" % n
        exp = os.path.join(d, "expected%s.txt" % suf)
        if not os.path.exists(exp):
            return res
        inp = os.path.join(d, "input%s.txt" % suf)
        res.append((read(inp) if os.path.exists(inp) else "", read(exp)))
        n += 1


def compile_text(code, name=None):
    return toolchain().compile({name or sandbox.file_name_for(code): code})


class CoursePrograms(unittest.TestCase):
    def test_every_course_program(self):
        tc = toolchain()
        self.assertTrue(tc.jdbc_available, "H2 / jdbc:mysql shim not available")
        failures, count = [], 0
        total = sum(len(cases(d)) for d in course_programs())
        for d in course_programs():
            files = {f: read(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.endswith(".java")}
            c = tc.compile(files)
            try:
                if not c.ok:
                    failures.append("%s: compile\n%s" % (os.path.basename(d), c.text()))
                    continue
                for i, (inp, exp) in enumerate(cases(d), 1):
                    r = tc.run(c, inp, setup_sql=sandbox.setup_sql_for(d))
                    count += 1
                    if sandbox.normalise(r.stdout) != sandbox.normalise(exp):
                        failures.append("%s case %d:\n--- expected\n%s\n--- got\n%s\n--- stderr\n%s"
                                        % (os.path.basename(d), i, exp, r.stdout, r.stderr))
            finally:
                c.cleanup()
        print("course cases run:", count)
        self.assertEqual(failures, [], "\n\n".join(failures))
        self.assertEqual(count, total)


HOSTILE = r'''
import java.nio.file.*;
public class Main {
  static void t(String n, Runnable r){ try { r.run(); System.out.println(n+"=ALLOWED"); } catch (Throwable e) { System.out.println(n+"=blocked"); } }
  static void io(java.util.concurrent.Callable<?> c) { try { c.call(); } catch (Exception e) { throw new RuntimeException(e); } }
  public static void main(String[] a) {
    t("own", () -> io(() -> Files.writeString(Path.of("ok.txt"), "x")));
    t("etc", () -> io(() -> Files.readString(Path.of("/etc/hostname"))));
    t("app", () -> io(() -> Files.list(Path.of(System.getProperty("user.dir"), "..")).count()));
    t("environ", () -> io(() -> Files.readAllBytes(Path.of("/proc/self/environ"))));
    t("parentenv", () -> io(() -> Files.readAllBytes(Path.of("/proc/1/environ"))));
    t("getenv", () -> System.getenv().size());
    t("exec", () -> io(() -> new ProcessBuilder("id").start()));
    t("processes", () -> ProcessHandle.allProcesses().count());
    t("socket", () -> io(() -> { new java.net.Socket("1.1.1.1", 80).close(); return null; }));
    t("reflect", () -> io(() -> { var f = String.class.getDeclaredField("value"); f.setAccessible(true); return null; }));
    t("loader", () -> new java.net.URLClassLoader(new java.net.URL[0]));
    t("unsm", () -> System.setSecurityManager(null));
  }
}
'''


class Containment(unittest.TestCase):
    def test_hostile_operations_blocked(self):
        c = compile_text(HOSTILE)
        try:
            self.assertTrue(c.ok, c.text())
            r = toolchain().run(c, "")
        finally:
            c.cleanup()
        got = dict(l.split("=") for l in r.stdout.split() if "=" in l)
        self.assertEqual(got.pop("own"), "ALLOWED", r.stdout + r.stderr)
        self.assertTrue(got and all(v == "blocked" for v in got.values()), got)
        self.assertEqual(r.files.get("ok.txt"), "x")
        self.assertNotIn("Security Manager is deprecated", r.stderr)

    def test_endless_loop_times_out(self):
        c = compile_text("public class Main { public static void main(String[] a) { while (true) { } } }")
        try:
            t0 = time.monotonic()
            r = toolchain().run(c, "", time_limit=3)
        finally:
            c.cleanup()
        self.assertTrue(r.timed_out)
        self.assertEqual(r.outcome, "timeout")
        self.assertLess(time.monotonic() - t0, 8)

    def test_output_flood_is_cut(self):
        c = compile_text('public class Main { public static void main(String[] a) { while (true) System.out.println("x".repeat(100)); } }')
        try:
            r = toolchain().run(c, "")
        finally:
            c.cleanup()
        self.assertTrue(r.output_limited)
        self.assertLessEqual(len(r.stdout.encode()), sandbox.MAX_STDOUT)

    def test_thread_and_memory_bombs_are_bounded(self):
        code = ('public class Main { public static void main(String[] a) { int n = 0; try { while (true) { Thread t = new Thread(() -> {'
                ' try { Thread.sleep(60000); } catch (Exception e) { } }); t.setDaemon(true); t.start(); n++; } } catch (Throwable e) {'
                ' System.out.println("threads " + n); } java.util.List<byte[]> m = new java.util.ArrayList<>(); try { while (true) m.add(new byte[1 << 20]); }'
                ' catch (Throwable e) { System.out.println("heap " + m.size()); } } }')
        c = compile_text(code)
        try:
            r = toolchain().run(c, "")
        finally:
            c.cleanup()
        threads = int(r.stdout.split("threads ")[1].split()[0])
        heap = int(r.stdout.split("heap ")[1].split()[0])
        self.assertLess(threads, 400)
        self.assertLessEqual(heap, 128)

    def test_big_file_is_refused(self):
        code = ('import java.io.*; public class Main { public static void main(String[] a) throws Exception {'
                ' try (FileOutputStream f = new FileOutputStream("big.bin")) { byte[] b = new byte[1 << 16];'
                ' for (int i = 0; i < 64; i++) f.write(b); System.out.println("wrote"); } catch (IOException e) { System.out.println("refused"); } } }')
        c = compile_text(code)
        try:
            r = toolchain().run(c, "")
        finally:
            c.cleanup()
        self.assertNotIn("wrote", r.stdout)

    def test_parallel_runs(self):
        c = compile_text("import java.util.*; public class Main { public static void main(String[] a) { Scanner s = new Scanner(System.in);"
                         " int x = s.nextInt(); System.out.println(x * x); } }")
        results = {}

        def go(i):
            results[i] = toolchain().run(c, "%d\n" % i).stdout.strip()
        try:
            ts = [threading.Thread(target=go, args=(i,)) for i in range(12)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        finally:
            c.cleanup()
        self.assertEqual(results, {i: str(i * i) for i in range(12)})


class Compiler(unittest.TestCase):
    def test_compile_error_has_line(self):
        c = compile_text("public class Main {\n  public static void main(String[] a) {\n    int x = 5\n  }\n}\n")
        c.cleanup()
        self.assertFalse(c.ok)
        self.assertTrue(any(d.line == 3 and "';' expected" in d.message for d in c.diagnostics), c.text())
        self.assertIn("Main.java:3: error: ';' expected", c.text())

    def test_main_class_rule_matches_gradebook(self):
        sys.path.insert(0, os.path.join(ROOT, "lab-system", "grader"))
        import grade
        import tempfile
        samples = {"Main.java": "class A {} public class Main { public static void main(String[] a) {} }",
                   "Rect.java": "public class Rect { public static void main(String[] a) {} }",
                   "Calc.java": "class Calc { public static void main(String[] a) {} }"}
        for name, text in samples.items():
            d = tempfile.mkdtemp()
            p = os.path.join(d, name)
            with open(p, "w") as f:
                f.write(text)
            self.assertEqual(sandbox.main_class({name: text}), grade.main_class([p]), name)

    def test_warm_compile_is_fast(self):
        code = read(os.path.join(ROOT, "course", "experiments", "E04a-employee-bonus-inheritance", "Main.java"))
        times = []
        for _ in range(5):
            c = compile_text(code)
            c.cleanup()
            self.assertTrue(c.ok)
            times.append(c.ms)
        print("warm compile ms:", times)
        self.assertLess(min(times), 1500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
