#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <detector.engine> <recognizer.engine> <output_zip>"
  exit 1
fi

DETECTOR_ENGINE="$1"
RECOGNIZER_ENGINE="$2"
OUTPUT_ZIP="$3"

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

cp "$DETECTOR_ENGINE" "$TMP_DIR/detector.engine"
cp "$RECOGNIZER_ENGINE" "$TMP_DIR/recognizer.engine"

(
  cd "$TMP_DIR"
  zip -q -r "$OUTPUT_ZIP" detector.engine recognizer.engine
)

echo "Portable model ZIP created: $OUTPUT_ZIP"
