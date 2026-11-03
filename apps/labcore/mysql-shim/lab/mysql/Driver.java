package lab.mysql;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.AccessController;
import java.security.PrivilegedAction;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.DriverPropertyInfo;
import java.sql.SQLException;
import java.sql.SQLFeatureNotSupportedException;
import java.sql.Statement;
import java.util.Properties;
import java.util.logging.Logger;

/**
 * "jdbc:mysql://..." for the Java Lab student app: an in-memory H2 database in MySQL mode, so
 * that Experiment 16 (JDBC) runs without a MySQL server. Each program run starts with an empty
 * database; the question's setup.sql (system property lab.mysql.setup) creates its tables.
 * The real MySQL server is used by CI (.github/workflows/ci.yml, job jdbc-experiment).
 */
public final class Driver implements java.sql.Driver {
    static {
        try {
            DriverManager.registerDriver(new Driver());
        } catch (SQLException e) {
            throw new ExceptionInInitializerError(e);
        }
    }

    private static boolean ready;

    @Override
    public boolean acceptsURL(String url) {
        return url != null && url.startsWith("jdbc:mysql:");
    }

    @Override
    public Connection connect(String url, Properties info) throws SQLException {
        if (!acceptsURL(url)) {
            return null;
        }
        String rest = url.substring("jdbc:mysql:".length()).replaceFirst("^//[^/]*", "");
        String db = rest.replaceFirst("^/", "").replaceFirst("[?;].*$", "");
        if (db.isEmpty()) {
            db = "test";
        }
        if (!db.matches("[A-Za-z0-9_]{1,64}")) {
            throw new SQLException("Unknown database '" + db + "'", "42000", 1049);
        }
        String h2 = "jdbc:h2:mem:" + db + ";MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1";
        Connection c = AccessController.doPrivileged((PrivilegedAction<Connection>) () -> {
            try {
                return new org.h2.Driver().connect(h2, new Properties());
            } catch (SQLException e) {
                throw new IllegalStateException(e);
            }
        });
        synchronized (Driver.class) {
            if (!ready) {
                ready = true;
                setup(c);
            }
        }
        return c;
    }

    private static void setup(Connection c) throws SQLException {
        String path = System.getProperty("lab.mysql.setup", "");
        if (path.isEmpty()) {
            return;
        }
        String sql = AccessController.doPrivileged((PrivilegedAction<String>) () -> {
            try {
                return Files.readString(Paths.get(path), StandardCharsets.UTF_8);
            } catch (java.io.IOException e) {
                return "";
            }
        });
        try (Statement st = c.createStatement()) {
            for (String part : sql.split(";")) {
                String s = part.strip();
                String u = s.toUpperCase(java.util.Locale.ROOT);
                if (s.isEmpty() || u.startsWith("CREATE DATABASE") || u.startsWith("USE ") || u.startsWith("DROP DATABASE")) {
                    continue;
                }
                st.execute(s);
            }
        }
    }

    @Override public DriverPropertyInfo[] getPropertyInfo(String url, Properties info) { return new DriverPropertyInfo[0]; }
    @Override public int getMajorVersion() { return 8; }
    @Override public int getMinorVersion() { return 4; }
    @Override public boolean jdbcCompliant() { return false; }
    @Override public Logger getParentLogger() throws SQLFeatureNotSupportedException { throw new SQLFeatureNotSupportedException(); }
}
