#!/usr/bin/env bash
# One-time set-up of the Java Lab on a new GitHub account. Run it in a Codespace of your new
# public repository (for example YOU/Java) after unzipping Java-main-streamlit.zip there:
#
#     bash Java-main/tools/setup_new_account.sh
#
# It (1) puts the platform into the repository and points every address to it, (2) checks it,
# (3) makes the teacher key pair, (4) pushes the lab repository, (5) builds and pushes your
# PRIVATE gradebook YOU/java-lab-gradebook (which must exist, empty), (6) stores the private key
# as the gradebook secret LAB_PRIVATE_KEY. It asks once for a fine-grained "setup token" with
# Contents, Workflows and Secrets read/write on both repositories (docs/11-streamlit-apps.md).
set -euo pipefail

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { printf '\n\033[31mSTOPPED: %s\033[0m\n' "$*" >&2; exit 1; }

TOP=$(git rev-parse --show-toplevel 2>/dev/null) || die "run this inside the Codespace of your repository"
cd "$TOP"
ORIGIN=$(git remote get-url origin)
SLUG=$(printf '%s' "$ORIGIN" | sed -E 's#^.*github\.com[:/]##; s#\.git$##; s#/$##')
OWNER=${SLUG%%/*}
REPO=${SLUG#*/}
BOOK="$OWNER/java-lab-gradebook"
BASE=${LAB_SETUP_REMOTE_BASE:-https://github.com}     # tests use a local folder instead of GitHub
[ -n "$OWNER" ] && [ -n "$REPO" ] || die "cannot read the repository from origin ($ORIGIN)"
echo "Lab repository: $SLUG    gradebook: $BOOK"

say "1. Platform files into $SLUG"
if [ -d Java-main ] && [ -f Java-main/README.md ]; then
  rm -f README.md
  cp -a Java-main/. .
  rm -rf Java-main
  rm -f Java-main-streamlit.zip
fi
[ -f tools/set_owner.py ] || die "Java-main not found: unzip Java-main-streamlit.zip in $TOP first"
grep -qx 'lab-private-key.pem' .gitignore || printf 'lab-private-key.pem\n' >> .gitignore
chmod +x android-app/gradlew lab-system/grader/sandbox.sh lab-system/selftest/make_samples.sh tools/*.sh \
  tools/browser-javac/build.sh starter-template/build.sh tools/set_owner.py   # in case the ZIP lost them
python3 tools/set_owner.py "$SLUG"

say "2. Checks"
python3 -c "import cryptography" 2>/dev/null || python3 -m pip install -q --user cryptography==46.0.3 2>/dev/null \
  || python3 -m pip install -q --break-system-packages cryptography==46.0.3 || die "could not install the Python package cryptography"
python3 tools/validate_projects.py || die "project check failed"
python3 tools/render_problem_bank.py --check || die "problem bank check failed"
out=$(python3 tools/lab/test_lab.py 2>&1) || { echo "$out" | tail -20; die "lab system tests failed"; }
echo "lab system tests: $(echo "$out" | tail -1)"
if command -v java >/dev/null && java -XshowSettings:properties -version 2>&1 | grep -Eq 'java.specification.version = (2[1-9]|[3-9][0-9])'; then
  java tools/CourseCheck.java | tail -1
else
  echo "(Java 21 not in this Codespace: the course programs are checked by CI on GitHub)"
fi

say "3. Teacher key pair"
if [ -f lab/teacher-public-key.pem ] && [ -f lab-private-key.pem ]; then
  echo "Key pair exists already (lab/teacher-public-key.pem, lab-private-key.pem): kept."
else
  tmp=$(mktemp -d)
  kout=$(python3 tools/lab/labcrypto.py keygen "$tmp") || die "key pair not created"
  printf '%s\n' "$kout" | sed -n 1p
  mv "$tmp/teacher-public-key.pem" lab/teacher-public-key.pem
  mv "$tmp/lab-private-key.pem" lab-private-key.pem
  chmod 600 lab-private-key.pem
  rm -rf "$tmp"
fi
git check-ignore -q lab-private-key.pem || die "lab-private-key.pem would be committed; stopping"

say "4. Push $SLUG"
printf 'Paste the setup token (nothing is shown), then press Enter: '
read -rs TOKEN; echo
[ -n "$TOKEN" ] || die "no token given"
AUTH="Authorization: Basic $(printf '%s:%s' "$OWNER" "$TOKEN" | base64 | tr -d '\n')"
gitpush() { git -c credential.helper= -c "http.extraHeader=$AUTH" push "$@"; }
git add -A
git -c user.name="${GIT_AUTHOR_NAME:-$OWNER}" -c user.email="${GIT_AUTHOR_EMAIL:-$OWNER@users.noreply.github.com}" \
  commit -q -m "Java Lab platform" || echo "(nothing new to commit)"
gitpush "$BASE/$SLUG.git" HEAD:main || die "push to $SLUG refused: check the setup token (repositories, Contents and Workflows read/write)"

say "5. Private gradebook $BOOK"
if git -c credential.helper= -c "http.extraHeader=$AUTH" ls-remote "$BASE/$BOOK.git" main 2>/dev/null | grep -q .; then
  echo "The gradebook has content already: kept (it may hold results)."
else
work=$(mktemp -d)
python3 lab-system/package.py course "$work" >/dev/null
(cd "$work" && python3 -c "import zipfile; zipfile.ZipFile('java-lab-gradebook.zip').extractall('.')")
(
  cd "$work/java-lab-gradebook"
  git init -q -b main
  git add -A
  git -c user.name="${GIT_AUTHOR_NAME:-$OWNER}" -c user.email="${GIT_AUTHOR_EMAIL:-$OWNER@users.noreply.github.com}" \
    commit -q -m "Java Lab gradebook"
  git -c credential.helper= -c "http.extraHeader=$AUTH" push -q "$BASE/$BOOK.git" main 2>&1 | grep -v '^remote:' || true
  git -c credential.helper= -c "http.extraHeader=$AUTH" ls-remote "$BASE/$BOOK.git" main | grep -q . \
    || { echo "push to $BOOK failed: create it first (private, empty) and include it in the token" >&2; exit 1; }
) || die "gradebook not pushed"
echo "Gradebook pushed: $(find "$work/java-lab-gradebook" -type f -not -path '*/.git/*' | wc -l) files"
rm -rf "$work"
fi

say "6. Secret LAB_PRIVATE_KEY in $BOOK"
if [ -n "${LAB_SETUP_SKIP_SECRET:-}" ]; then
  echo "(skipped by LAB_SETUP_SKIP_SECRET)"
elif command -v gh >/dev/null; then
  GH_TOKEN="$TOKEN" gh secret set LAB_PRIVATE_KEY --repo "$BOOK" < lab-private-key.pem \
    && GH_TOKEN="$TOKEN" gh secret list --repo "$BOOK" | grep -q '^LAB_PRIVATE_KEY' \
    || die "secret not stored: the token needs Secrets read/write on $BOOK"
  echo "Secret stored."
else
  echo "gh is not installed: add the secret by hand (docs/11-streamlit-apps.md, step 6)."
fi
unset TOKEN AUTH

say "Done"
cat <<EOF
Lab repository : https://github.com/$SLUG
Website        : https://${OWNER,,}.github.io/$REPO/   (ready when Actions shows the Pages run green)
Gradebook      : https://github.com/$BOOK   (private)
Key id         : $(python3 -c "import sys; sys.path.insert(0,'tools/lab'); import labcrypto; print(labcrypto.key_id(open('lab/teacher-public-key.pem').read()))")

NOW: in the file list on the left, right-click lab-private-key.pem, Download, keep it safe
(password manager or encrypted drive), then delete it here:   rm lab-private-key.pem
EOF
