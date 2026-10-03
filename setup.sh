#!/bin/sh
# Builds your personal copy of the extension in ./extension with a fresh secret code.
# Optional: put PROJECT_URL=<a claude.ai project link> in .env to file searches in that project.
set -e
cd "$(dirname "$0")"
token=$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')
project=""
if [ -f .env ]; then
  value=$(sed -n 's/^[[:space:]]*PROJECT_URL[[:space:]]*=//p' .env | head -n1 | tr -d '\r')
  project=$(printf '%s' "$value" | grep -oE '[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}' | head -n1 || true)
  if [ -n "$(printf '%s' "$value" | tr -d ' "'"'")" ] && [ -z "$project" ]; then
    echo "PROJECT_URL in .env has no project id in it (expected https://claude.ai/project/<id>)." >&2
    exit 1
  fi
fi
mkdir -p extension
for f in src/*; do
  sed -e "s/__TOKEN__/$token/" -e "s/__PROJECT__/${project:-__PROJECT__}/" "$f" > "extension/$(basename "$f")"
done
if [ -n "$project" ]; then
  echo "Searches will start in claude.ai project $project."
fi
echo "Built ./extension. Load it in brave://extensions (or chrome://extensions) with 'Load unpacked'."
