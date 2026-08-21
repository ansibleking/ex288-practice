#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/swagger.json"
BASE="${TAMS_BASE_URL:-https://tams.emaratech.ae}"

mkdir -p "$ROOT/specs"

echo "Fetching OpenAPI spec from $BASE ..."

for path in \
  "/swagger/v1/swagger.json" \
  "/swagger/v1/swagger.yaml" \
  "/swagger/swagger.json" \
  "/swagger/doc.json"
do
  if curl -fsS "$BASE$path" -o "$OUT"; then
    echo "Saved $OUT"
    exit 0
  fi
done

echo "Could not download swagger spec. Ensure VPN is connected and try:"
echo "  curl -o $OUT $BASE/swagger/v1/swagger.json"
exit 1
