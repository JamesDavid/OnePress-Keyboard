"""Build the demo page from web/page.template.html.

Usage: python web/build_page.py [out.html] [--lazy]

Without --lazy (web/keypad.html) the decoder and the English models are built in, so the page
works offline, even opened as a file; the other languages (every onepress-<lang>[-m|-s].bin in
model/) are fetched when first picked. With
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
for tag, f in [("L", "onepress.bin"), ("M", "onepress-m.bin"), ("S", "onepress-s.bin")]:
    data = open(os.path.join(ROOT, "model", f), "rb").read()
    t = t.replace(f"__SIZE_{tag}__", str(len(data)))
    t = t.replace(f"__WORDS_{tag}__", str(struct.unpack_from("<H", data, 8)[0]))
    t = t.replace(f"__MODEL_{tag}__", "" if lazy else base64.b64encode(data).decode())
# Other languages, fetched when picked: a menu group each, in the three sizes that exist.
LANGS = [("es", "Español"), ("de", "Deutsch"), ("pt", "Português"), ("fr", "Français"), ("it", "Italiano"),
         ("nl", "Nederlands"), ("sv", "Svenska"), ("pl", "Polski"), ("cs", "Čeština"), ("tr", "Türkçe"),
         ("ru", "Русский"), ("el", "Ελληνικά")]
SIZES = [("", "Phone / web"), ("-m", "ESP32"), ("-s", "Radio")]
scripts, menu = [], []
for code, name in LANGS:
    for suf, device in SIZES:
        f = f"onepress-{code}{suf}.bin"
        p = os.path.join(ROOT, "model", f)
        if not os.path.exists(p):
            continue
        data = open(p, "rb").read()
        mid = code + suf
        scripts.append(f'<script type="application/octet-stream" id="model-{mid}" data-file="{f}" data-size="{len(data)}" '
                       f'data-words="{struct.unpack_from("<H", data, 8)[0]}"></script>')
        menu.append(f"    {{ id: '{mid}', name: '{device}', device: '{device}', group: '{name}', el: 'model-{mid}', lang: '{code}' }},")
t = t.replace("__LANG_SCRIPTS__", "\n".join(scripts)).replace("__LANG_MENU__", "\n".join(menu))
open(out, "w", encoding="utf-8", newline="\n").write(t)
print(f"wrote {out} ({os.path.getsize(out):,} bytes{', models fetched on demand' if lazy else ''})")
