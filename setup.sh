#!/bin/sh
# Builds your personal copy of the extension in ./extension with a fresh secret code.
set -e
cd "$(dirname "$0")"
token=$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')
mkdir -p extension
for f in manifest.json autosend.js; do
  sed "s/__TOKEN__/$token/" "src/$f" > "extension/$f"
done
echo "Built ./extension. Load it in brave://extensions (or chrome://extensions) with 'Load unpacked'."
