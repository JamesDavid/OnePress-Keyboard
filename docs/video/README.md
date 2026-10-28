# Keypad tutorial video

The narrated phone keypad tutorial linked from the main README. It is made from the real demo page,
so re-render it after changing the page or the decoder:

```sh
bash docs/video/make.sh        # build/video/onepress-keypad-tutorial.mp4 and .srt, about 4 minutes
```

- `scenes.py`: the script. Each scene is a title and steps: narration lines (the caption, and how
  it's spoken when that differs: "pound", "star"), key presses (`H4` holds 4), taps on a guess, Send.
  Each line starts once the one before has finished.
- `tts.py`: speaks the lines with [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) (Apache 2.0,
  runs locally, voice `af_heart`; `VOICE=am_michael bash make.sh` for another). Clips are cached.
- `record.py`: drives `web/keypad.html` in Chromium (served over http, so Neural is on as on the live
  demo) inside a 1920×1080 frame with the captions and the keys pressed, and records it with the
  Chrome DevTools screencast. `python record.py --dry` prints what each scene ends with.
- `assemble.py`: the frames at 30 fps, each clip placed when it started, and an `.srt` of the lines.

The video isn't kept in the repository. GitHub plays a README video only when it was uploaded on
github.com: drag the new MP4 into the README in the web editor (or into an unsent issue comment
to get a link) and replace the link in `README.md`.
