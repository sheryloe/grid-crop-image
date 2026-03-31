#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <detector.onnx> <recognizer.onnx> <output_model_dir>"
  exit 1
fi

DETECTOR_ONNX="$1"
RECOGNIZER_ONNX="$2"
OUT_DIR="$3"

mkdir -p "$OUT_DIR"

# Requires NVIDIA TensorRT's trtexec in PATH.
trtexec --onnx="$DETECTOR_ONNX" --saveEngine="$OUT_DIR/detector.engine" --fp16
trtexec --onnx="$RECOGNIZER_ONNX" --saveEngine="$OUT_DIR/recognizer.engine" --fp16

echo "TensorRT engines generated in: $OUT_DIR"
