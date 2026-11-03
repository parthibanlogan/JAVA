"""A Java 21 JDK for the student app.

Streamlit Community Cloud runs on Debian 11, whose packages stop at Java 17, while the gradebook
marks with Eclipse Temurin 21 (lab-system/grader). The app therefore downloads the same Temurin 21
JDK once per container start, checks its SHA-256 and unpacks it into a cache folder.

Order of preference: $LAB_JAVA_HOME, the cached Temurin download, a JDK 21+ already on PATH.
"""
import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

VERSION = "21.0.13+9"
SHA256 = {  # from the .sha256.txt files published with the release
    "x64": "d7f5d5cf865a2902b70ff549b97586a7d3f234e016f041ab447ea740c7d66d1c",
    "aarch64": "e3522e707fc7dbe2a72c30746b1e7068301a0213ecd213d4491f35a14eb55578",
}
ARCH = {"x86_64": "x64", "amd64": "x64", "aarch64": "aarch64", "arm64": "aarch64"}


class JdkError(RuntimeError):
    pass


def _url(arch):
    tag = "jdk-" + VERSION.replace("+", "%2B")
    name = "OpenJDK21U-jdk_%s_linux_hotspot_%s.tar.gz" % (arch, VERSION.replace("+", "_"))
    return "https://github.com/adoptium/temurin21-binaries/releases/download/%s/%s" % (tag, name)


def cache_dir():
    base = os.environ.get("LAB_CACHE") or os.path.join(os.path.expanduser("~"), ".cache", "javalab")
    try:
        os.makedirs(base, exist_ok=True)
        probe = os.path.join(base, ".w")
        open(probe, "w").close()
        os.remove(probe)
        return base
    except OSError:
        base = os.path.join(tempfile.gettempdir(), "javalab")
        os.makedirs(base, exist_ok=True)
        return base


def _major(java_home):
    """Feature version of the JDK at java_home (e.g. 21), or 0 when it is not a usable JDK."""
    javac = os.path.join(java_home, "bin", "javac")
    java = os.path.join(java_home, "bin", "java")
    if not (os.access(javac, os.X_OK) and os.access(java, os.X_OK)):
        return 0
    try:
        out = subprocess.run([java, "-XshowSettings:properties", "-version"], capture_output=True,
                             text=True, timeout=60).stderr
    except (OSError, subprocess.SubprocessError):
        return 0
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("java.specification.version ="):
            try:
                return int(line.split("=", 1)[1].strip())
            except ValueError:
                return 0
    return 0


def _download(arch, dest, log):
    url = _url(arch)
    log("Downloading Temurin %s (%s) ..." % (VERSION, arch))
    tmp = dest + ".part"
    digest = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "java-lab-streamlit"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
            f.write(chunk)
    if digest.hexdigest() != SHA256[arch]:
        os.remove(tmp)
        raise JdkError("checksum mismatch for %s" % url)
    os.replace(tmp, dest)


def _safe_extract(archive, target):
    with tarfile.open(archive, "r:gz") as tar:
        root = os.path.realpath(target)
        for m in tar.getmembers():
            p = os.path.realpath(os.path.join(target, m.name))
            if os.path.commonpath([root, p]) != root:
                raise JdkError("unsafe path in archive: %s" % m.name)
        try:
            tar.extractall(target, filter="tar")
        except TypeError:  # Python < 3.12 without extraction filters
            tar.extractall(target)


def ensure_jdk(log=lambda msg: None):
    """Returns JAVA_HOME of a JDK 21 or newer; downloads Temurin 21 if needed."""
    env_home = os.environ.get("LAB_JAVA_HOME")
    if env_home and _major(env_home) >= 21:
        return env_home
    arch = ARCH.get(platform.machine().lower())
    base = cache_dir()
    home = os.path.join(base, "jdk-" + VERSION)
    if _major(home) >= 21:
        return home
    if arch:
        try:
            archive = os.path.join(base, "temurin-%s-%s.tar.gz" % (VERSION.replace("+", "_"), arch))
            if not os.path.exists(archive):
                _download(arch, archive, log)
            work = tempfile.mkdtemp(dir=base)
            _safe_extract(archive, work)
            tops = [d for d in os.listdir(work) if os.path.isdir(os.path.join(work, d))]
            if len(tops) != 1:
                raise JdkError("unexpected archive layout")
            shutil.rmtree(home, ignore_errors=True)
            os.replace(os.path.join(work, tops[0]), home)
            shutil.rmtree(work, ignore_errors=True)
            os.remove(archive)
            if _major(home) >= 21:
                return home
        except (OSError, JdkError, tarfile.TarError) as e:
            log("Temurin download failed: %s" % e)
    javac = shutil.which("javac")
    if javac:
        cand = os.path.dirname(os.path.dirname(os.path.realpath(javac)))
        if _major(cand) >= 21:
            return cand
    raise JdkError("no Java 21 JDK available (download failed and none on PATH)")
