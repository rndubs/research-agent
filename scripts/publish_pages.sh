#!/usr/bin/env bash
# Publish the rendered backlog/digest to docs/ for GitHub Pages.
#
# Point Pages at this branch, folder /docs (Settings -> Pages -> Deploy from a
# branch -> /docs). The nightly cycle runs this after `batch-apply`, then commits
# docs/ alongside state/.
set -euo pipefail

src="${1:-state/output}"
dst="${2:-docs}"
mkdir -p "$dst"

if [ -f "$src/digest.html" ]; then
  cp "$src/digest.html" "$dst/index.html"
fi
[ -f "$src/backlog.md" ] && cp "$src/backlog.md" "$dst/backlog.md"
[ -f "$src/digest.md" ] && cp "$src/digest.md" "$dst/digest.md"
touch "$dst/.nojekyll"   # serve files as-is (no Jekyll build)

echo "published '$src' -> '$dst/' (Pages: Deploy from branch, folder /docs)"
