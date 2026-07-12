#!/usr/bin/env bash
set -euo pipefail

echo "Candidate temp files. Review manually before deleting:"
find /tmp -maxdepth 1 \( \
  -name 'direct_dl*.py' -o \
  -name 'sites_b64.txt' -o \
  -name 'check_*.py' \
\) -print 2>/dev/null || true

cat <<'EOF'

This script does not delete files automatically.
After review, delete individual files with:
rm -i /tmp/file-name
EOF
