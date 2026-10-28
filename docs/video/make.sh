#!/usr/bin/env bash
# Renders the narrated keypad tutorial (docs/video/README.md): build/video/onepress-keypad-tutorial.mp4 and .srt.
# Needs Python with playwright (python -m playwright install chromium) and ffmpeg on PATH; the narration
# voice (Kokoro, Apache 2.0, runs locally) is installed into build/video/tts on the first run.
set -e
cd "$(dirname "$0")"
W=../../build/video
mkdir -p $W/kokoro
if [ ! -d $W/tts ]; then
  python -m venv $W/tts
  $W/tts/Scripts/pip install -q kokoro-onnx soundfile 2>/dev/null || $W/tts/bin/pip install -q kokoro-onnx soundfile
fi
PY=$W/tts/Scripts/python; [ -x $PY ] || PY=$W/tts/bin/python
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  [ -f $W/kokoro/$f ] || curl -sSL -o $W/kokoro/$f https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f
done
(cd ../../web && python build_page.py)
$PY tts.py "${VOICE:-af_heart}"
python record.py
python assemble.py
