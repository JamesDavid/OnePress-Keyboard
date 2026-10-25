"""Build the demo page from web/page.template.html.

Usage: python web/build_page.py [out.html] [--lazy]

Without --lazy (web/keypad.html) the decoder and the English models are built in, so the page
works offline, even opened as a file; the other languages are fetched when first picked. With
--lazy (the GitHub Pages index.html) only the decoder is: each model is fetched when it is first
picked, from the same folder (onepress.bin, onepress-es.bin, ...) or ../model/.
"""
import base64, os, struct, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = [a for a in sys.argv[1:] if a != "--lazy"]
lazy = "--lazy" in sys.argv
out = args[0] if args else os.path.join(ROOT, "web", "keypad.html")

t = open(os.path.join(ROOT, "web", "page.template.html"), encoding="utf-8").read()
t = t.replace("__DECODER__", open(os.path.join(ROOT, "web", "decoder.js"), encoding="utf-8").read())
for tag, f, inline in [("L", "onepress.bin", True), ("M", "onepress-m.bin", True), ("S", "onepress-s.bin", True),
                       ("ES", "onepress-es.bin", False), ("DE", "onepress-de.bin", False), ("PT", "onepress-pt.bin", False),
                       ("FR", "onepress-fr.bin", False)]:
    data = open(os.path.join(ROOT, "model", f), "rb").read()
    t = t.replace(f"__SIZE_{tag}__", str(len(data)))
    t = t.replace(f"__WORDS_{tag}__", str(struct.unpack_from("<H", data, 8)[0]))
    t = t.replace(f"__MODEL_{tag}__", "" if lazy or not inline else base64.b64encode(data).decode())
open(out, "w", encoding="utf-8", newline="\n").write(t)
print(f"wrote {out} ({os.path.getsize(out):,} bytes{', models fetched on demand' if lazy else ''})")
