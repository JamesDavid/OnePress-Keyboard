"""Render the README demo GIFs: the keypad (or the QWERTY layout) typing a sentence, each press
marked by a circle that appears on the key and grows as it fades.
Usage: python docs/record_demo.py docs/demo.gif [--qwerty]
(needs: pip install playwright pillow; playwright install chromium)"""
import io, sys
from PIL import Image
from playwright.sync_api import sync_playwright

URL = "file:///C:/Users/James/Desktop/Projects/OnePress_Keyboard/web/keypad.html"
KEYS = "44#066069092904663#0733096807666#"     # Hi! On my way home. See you soon.
QWERTY = "running late# start without me#"      # Running late, start without me.
W, H = 360, 600

OVERLAY = """
const d = document.createElement('div');
d.id = 'press';
Object.assign(d.style, { position: 'fixed', width: '64px', height: '64px', marginLeft: '-32px', marginTop: '-32px',
  borderRadius: '50%', border: '5px solid #ff2d20', background: 'rgba(255, 45, 32, 0.45)',
  boxShadow: '0 0 0 3px #fff, 0 2px 10px rgba(0,0,0,.35)', boxSizing: 'border-box',
  pointerEvents: 'none', zIndex: 9999, display: 'none' });
document.body.appendChild(d);
window.pressAt = (sel, scale, alpha) => {
  const r = document.querySelector(sel).getBoundingClientRect();
  Object.assign(d.style, { display: alpha > 0 ? 'block' : 'none', left: (r.x + r.width / 2) + 'px',
    top: (r.y + r.height / 2) + 'px', transform: `scale(${scale})`, opacity: alpha });
};
0;
"""

def main(out, qwerty):
    frames, durations = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": 680}, device_scale_factor=1)
        pg.add_init_script("localStorage.setItem('tutorialSeen','1'); localStorage.setItem('nn','0');"
                           "localStorage.removeItem('sent'); localStorage.removeItem('model');"
                           f"localStorage.setItem('kbMode', '{'qwerty' if qwerty else 'keypad'}');")
        pg.goto(URL)
        pg.wait_for_timeout(2500)
        pg.click("#clear")
        pg.evaluate(OVERLAY)
        pg.wait_for_timeout(300)

        def shot(ms):
            png = pg.screenshot(clip={"x": 0, "y": 0, "width": W, "height": H})
            frames.append(Image.open(io.BytesIO(png)).convert("RGB"))
            durations.append(ms)

        shot(900)
        for k in (QWERTY if qwerty else KEYS):
            sel = f'[data-qk="{"0" if k == " " else k}"]' if qwerty else f'[data-key="{k}"]'
            if qwerty and k == " ": k = "0"
            pg.evaluate(f"pressAt({sel!r}, 0.45, 1)")
            shot(70)
            pg.evaluate(f"document.querySelector({sel!r}).click()")
            pg.wait_for_timeout(30)
            for scale, alpha in ((0.75, 1), (1.0, 0.9), (1.25, 0.6), (1.45, 0.3)):
                pg.evaluate(f"pressAt({sel!r}, {scale}, {alpha})")
                shot(55)
            pg.evaluate(f"pressAt({sel!r}, 1, 0)")
            shot(450 if k == "#" else 300 if k == "0" else 170)
        shot(2600)
        print(pg.evaluate("document.querySelector('.lcd').innerText"))
        b.close()
    # One palette for every frame (from a strip of samples), so each frame stores only what changed.
    sample = Image.new("RGB", (W, H * 4))
    for i, f in enumerate(frames[1:len(frames):len(frames) // 4][:4]): sample.paste(f, (0, H * i))
    sample.paste(frames[2], (0, 0))
    ref = sample.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    pal = [f.quantize(palette=ref, dither=Image.Dither.NONE) for f in frames]
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=durations, loop=0, optimize=True, disposal=1)
    print(len(frames), "frames,", sum(durations) / 1000, "s")

if __name__ == "__main__":
    main(sys.argv[1], "--qwerty" in sys.argv)
