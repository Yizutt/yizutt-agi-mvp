#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${YIZUTT_PYTHON:-python}"
VERSION="$("$PYTHON_BIN" - <<'PY'
from pathlib import Path
import tomllib

data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
print(data["project"]["version"])
PY
)"
TARGET_TRIPLE="${TARGET_TRIPLE:-$(rustc -vV | awk '/host:/ {print $2}')}"
PACKAGE_NAME="${PACKAGE_NAME:-yizutt-${VERSION}-${TARGET_TRIPLE}}"
DIST_DIR="${DIST_DIR:-${ROOT_DIR}/dist}"
STAGE="${DIST_DIR}/${PACKAGE_NAME}"
ARCHIVE="${DIST_DIR}/${PACKAGE_NAME}.tar.gz"
CHECKSUM="${ARCHIVE}.sha256"
EXE_SUFFIX=""

if [[ "${TARGET_TRIPLE}" == *"windows"* ]]; then
  EXE_SUFFIX=".exe"
fi

if [[ -z "$DIST_DIR" || "$STAGE" == "/" || "$STAGE" == "$ROOT_DIR" ]]; then
  echo "Refusing unsafe package output path: $STAGE" >&2
  exit 2
fi

cargo build --workspace --locked --release

mkdir -p "$DIST_DIR"
rm -rf "$STAGE" "$ARCHIVE" "$CHECKSUM"
mkdir -p "$STAGE/bin"

cp "target/release/yizutt${EXE_SUFFIX}" "$STAGE/bin/yizutt${EXE_SUFFIX}"
cp "target/release/yizutt-runtime${EXE_SUFFIX}" "$STAGE/bin/yizutt-runtime${EXE_SUFFIX}"
cp -R python web examples scripts proto "$STAGE/"
cp pyproject.toml README.md README_CN.md LICENSE "$STAGE/"
if [[ -f requirements.txt ]]; then
  cp requirements.txt "$STAGE/"
fi

chmod +x "$STAGE/bin/yizutt${EXE_SUFFIX}" "$STAGE/bin/yizutt-runtime${EXE_SUFFIX}"
chmod +x "$STAGE/scripts/start_local_demo.sh" "$STAGE/scripts/package_binary.sh"

cat > "$STAGE/README_RELEASE.md" <<EOF
# Yizutt Binary Package

This package contains native launchers for ${TARGET_TRIPLE}.

## Requirements

- Python 3.11 or newer available as \`python3\` or \`python\`.
- Loopback ports available for the local Runtime and Web workbench.

## Commands

\`\`\`bash
bin/yizutt --help
bin/yizutt onboard
bin/yizutt capabilities
bin/yizutt evolve --write
bin/yizutt
\`\`\`

\`bin/yizutt\` sets \`PYTHONPATH\`, \`RUNTIME_BIN\`, \`YIZUTT_RUNTIME_BIN\`, and \`BUILD=0\` so the bundled Runtime binary is used by default.

Set \`YIZUTT_PYTHON=/path/to/python\` if Python is not available as \`python3\` or \`python\`.
EOF

(
  cd "$DIST_DIR"
  tar -czf "$ARCHIVE" "$PACKAGE_NAME"
)

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$ARCHIVE" > "$CHECKSUM"
elif command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$ARCHIVE" > "$CHECKSUM"
else
  echo "sha256 tool not found; checksum skipped" >&2
fi

cat <<EOF
Yizutt binary package created.

Directory: $STAGE
Archive:   $ARCHIVE
Checksum:  $CHECKSUM

Smoke test:
  $STAGE/bin/yizutt --help
EOF
