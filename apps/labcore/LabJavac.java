import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Locale;
import java.util.stream.Stream;
import javax.tools.Diagnostic;
import javax.tools.DiagnosticCollector;
import javax.tools.JavaCompiler;
import javax.tools.JavaFileObject;
import javax.tools.StandardJavaFileManager;
import javax.tools.ToolProvider;

/**
 * Compile server of the Java Lab student app (apps/labcore/sandbox.py).
 *
 * One JVM keeps the JDK compiler warm, so a compile takes tens of milliseconds instead of a
 * second and about 80 MB per student. It only compiles: student code is never executed here
 * (annotation processing is switched off), so a hostile program cannot reach this process.
 *
 * Protocol, one request per line on standard input:  ID TAB SOURCE_DIR TAB CLASS_DIR
 * Answer on standard output:  ID TAB OK(0|1) TAB N, then N lines  KIND TAB LINE TAB COLUMN TAB BASE64(message)
 */
public class LabJavac {
    public static void main(String[] args) throws IOException {
        JavaCompiler javac = ToolProvider.getSystemJavaCompiler();
        if (javac == null) {
            System.err.println("no system Java compiler: a JDK (not a JRE) is required");
            System.exit(2);
        }
        PrintStream out = new PrintStream(System.out, false, StandardCharsets.UTF_8);
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        System.setOut(new PrintStream(System.err, true, StandardCharsets.UTF_8)); // nothing else may write to the protocol stream
        out.println("READY");
        out.flush();
        String line;
        while ((line = in.readLine()) != null) {
            String[] f = line.split("\t", -1);
            if (f.length != 3) {
                continue;
            }
            List<String[]> diags = new ArrayList<>();
            boolean ok;
            try {
                ok = compile(javac, Paths.get(f[1]), Paths.get(f[2]), diags);
            } catch (OutOfMemoryError e) {
                System.exit(3); // the app restarts the server
                return;
            } catch (Throwable e) {
                ok = false;
                diags.add(new String[] {"ERROR", "0", "0", b64("compiler failure: " + e)});
            }
            StringBuilder b = new StringBuilder();
            b.append(f[0]).append('\t').append(ok ? '1' : '0').append('\t').append(diags.size()).append('\n');
            for (String[] d : diags) {
                b.append(String.join("\t", d)).append('\n');
            }
            out.print(b);
            out.flush();
        }
    }

    static boolean compile(JavaCompiler javac, Path src, Path classes, List<String[]> diags) throws IOException {
        List<Path> files = new ArrayList<>();
        try (Stream<Path> s = Files.list(src)) {
            s.filter(p -> p.toString().endsWith(".java")).sorted().forEach(files::add);
        }
        Files.createDirectories(classes);
        DiagnosticCollector<JavaFileObject> collector = new DiagnosticCollector<>();
        try (StandardJavaFileManager fm = javac.getStandardFileManager(collector, Locale.ENGLISH, StandardCharsets.UTF_8)) {
            List<String> opts = List.of("-d", classes.toString(), "-encoding", "UTF-8", "-Xlint:none",
                    "-proc:none", "-implicit:none", "-Xmaxerrs", "50", "-g", "-cp", classes.toString());
            Boolean ok = javac.getTask(null, fm, collector, opts, null, fm.getJavaFileObjectsFromPaths(files)).call();
            for (Diagnostic<? extends JavaFileObject> d : collector.getDiagnostics()) {
                String name = d.getSource() == null ? "" : Paths.get(d.getSource().getName()).getFileName().toString();
                diags.add(new String[] {d.getKind().name(), Long.toString(Math.max(0, d.getLineNumber())),
                        Long.toString(Math.max(0, d.getColumnNumber())), b64(name + "\u0000" + d.getMessage(Locale.ENGLISH))});
            }
            return Boolean.TRUE.equals(ok);
        }
    }

    static String b64(String s) {
        return Base64.getEncoder().encodeToString(s.getBytes(StandardCharsets.UTF_8));
    }
}
