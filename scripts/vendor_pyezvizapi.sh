#!/usr/bin/env bash
#
# Bundle (vendor) pyezvizapi into the integration.
#
# The integration needs a 2.x pyezvizapi for SD-card playback, but Home
# Assistant's built-in EZVIZ integration pins 1.x, and one Python environment can
# hold only one version. A custom integration that requires a version the
# built-in one rules out is exactly what hassfest's [REQUIREMENTS] check reports
# ("Requirement pyezvizapi==X is incompatible with pyezvizapi==1.0.5.0, which Home
# Assistant depends on"), so the library is shipped inside the integration and
# imported from there instead of being installed.
#
# This script refreshes that bundled copy. Usage:
#
#   scripts/vendor_pyezvizapi.sh 2.6.0         # fetch pyezvizapi==2.6.0 from PyPI
#   scripts/vendor_pyezvizapi.sh /path/to/pkg  # copy an already unpacked folder
#   scripts/vendor_pyezvizapi.sh               # refresh from DEFAULT_VERSION
#
# It copies the package unchanged, then rewrites only its import root from
# ``pyezvizapi`` to ``custom_components.ezviz_rtsp.pyezvizapi`` so its internal
# imports resolve to the bundled copy. Logger names, docstrings and thread names
# are left alone.
#
# After running it: review the diff, bump DEFAULT_VERSION below and the version
# named in CHANGELOG.md / README.md, then run `ruff check .` and the tests.
set -euo pipefail

DEFAULT_VERSION="2.5.1"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest="$here/custom_components/ezviz_rtsp/pyezvizapi"
root="custom_components.ezviz_rtsp.pyezvizapi"

src="${1:-$DEFAULT_VERSION}"

tmp=""
cleanup() { [ -n "$tmp" ] && rm -rf "$tmp"; }
trap cleanup EXIT

if [ -d "$src" ]; then
  pkg="$src"
  version="(local path: $src)"
else
  version="$src"
  tmp="$(mktemp -d)"
  echo "Fetching pyezvizapi==$version ..."
  python3 -m pip install --quiet --no-deps --target "$tmp" "pyezvizapi==$version"
  pkg="$tmp/pyezvizapi"
fi

[ -d "$pkg" ] || { echo "No pyezvizapi package at: $pkg" >&2; exit 1; }

echo "Bundling pyezvizapi $version into $dest ..."
rm -rf "$dest"
cp -R "$pkg" "$dest"
find "$dest" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$dest" -name '*.pyc' -delete

# Rewrite only the import lines: a leading indent, then `from`/`import` and the
# package name. Continuation lines and every other mention are untouched.
find "$dest" -name '*.py' -print0 \
  | xargs -0 sed -i.bak -E "s/^([[:space:]]*)(from|import) pyezvizapi/\1\2 $root/"
find "$dest" -name '*.bak' -delete

left="$(grep -rlE '^[[:space:]]*(from|import) pyezvizapi' "$dest" --include='*.py' || true)"
[ -z "$left" ] || { echo "Unrewritten imports remain in:" >&2; echo "$left" >&2; exit 1; }

echo "Done: $(find "$dest" -type f | wc -l | tr -d ' ') files."
echo "Next: review the diff, set DEFAULT_VERSION=\"$version\" here, update CHANGELOG.md/README.md,"
echo "      then run 'ruff check .' and the tests."
