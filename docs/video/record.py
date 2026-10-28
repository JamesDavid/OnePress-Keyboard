# Records the tutorial: drives keypad.html in Chromium inside a 1920x1080 frame with captions,
# captures it with the CDP screencast, and logs when each narration clip starts.
# Writes build/video/frames/*.jpg, frames.json and timeline.json. Serves the repo on port 8765 while it runs
# (over http the page finds model/onepress-nn.bin, so Neural is on as on the live demo).
import asyncio, base64, json, os, re, shutil, subprocess, sys, time
from playwright.async_api import async_playwright
from scenes import SCENES

HERE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'build', 'video'))   # work files
URL = 'http://localhost:8765/web/keypad.html'
DURS = json.load(open(os.path.join(HERE, 'clips', 'durations.json'), encoding='utf-8'))
DRY = '--dry' in sys.argv

SHELL = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
html,body{margin:0;height:100%;}
body{width:1920px;height:1080px;overflow:hidden;background:#DCE0E7;color:#1B2230;
  font-family:"Atkinson Hyperlegible","Segoe UI",sans-serif;display:flex;align-items:center;}
.phone{margin-left:150px;width:500px;height:900px;border-radius:44px;background:#1B2230;padding:14px;
  box-shadow:0 30px 70px rgba(27,34,48,.28),0 6px 16px rgba(27,34,48,.18);flex:none;}
iframe{width:500px;height:900px;border:0;border-radius:32px;background:#E7EAEF;display:block;}
.side{margin-left:120px;width:1000px;display:flex;flex-direction:column;gap:28px;}
.brand{font-family:"JetBrains Mono",monospace;font-size:22px;letter-spacing:.12em;text-transform:uppercase;color:#5B6577;}
.brand b{color:#2E52C4;font-weight:500;}
h1{font-family:"Bricolage Grotesque","Segoe UI",sans-serif;font-weight:700;font-size:76px;letter-spacing:-.02em;margin:0;line-height:1.05;}
.cap{font-size:40px;line-height:1.4;min-height:170px;max-width:960px;transition:opacity .25s;}
.keys{display:flex;flex-wrap:wrap;gap:10px;min-height:64px;align-items:center;}
.keys kbd{font-family:"JetBrains Mono",monospace;font-size:30px;min-width:56px;height:56px;padding:0 12px;box-sizing:border-box;
  display:inline-flex;align-items:center;justify-content:center;border-radius:12px;background:#fff;
  border:1px solid #C6CDD8;box-shadow:0 3px 0 #C6CDD8;}
.keys kbd.hold{background:#2E52C4;color:#fff;border-color:#2E52C4;box-shadow:0 3px 0 #1d3a96;}
.keys kbd.hold::after{content:" hold";font-size:18px;margin-left:6px;opacity:.85;}
.keys kbd.tap{font-family:"Atkinson Hyperlegible",sans-serif;font-size:24px;}
.keys .gap{width:18px;}
.dots{display:flex;gap:10px;}
.dots i{width:34px;height:6px;border-radius:3px;background:#C6CDD8;}
.dots i.on{background:#2E52C4;}
</style></head><body>
<div class="phone"><iframe id="kp"></iframe></div>
<div class="side">
  <div class="brand"><b>OnePress</b> &middot; phone keypad tutorial</div>
  <h1 id="title"></h1>
  <div class="dots" id="dots"></div>
  <div class="cap" id="cap"></div>
  <div class="keys" id="keys"></div>
</div></body></html>"""

# Injected into the keypad page: a touch marker where each press lands, growing while held.
TOUCH = """(() => {
  const st = document.createElement('style');
  st.textContent = `.notes{display:none!important}
  .tdot{position:fixed;width:46px;height:46px;margin:-23px 0 0 -23px;border-radius:50%;pointer-events:none;z-index:99;
    background:rgba(46,82,196,.28);border:2px solid rgba(46,82,196,.7);transition:transform .45s ease-out,opacity .3s;}
  .tdot.held{transform:scale(1.7);}
  .tdot.up{opacity:0;}`;
  document.head.appendChild(st);
  let cur = null;
  addEventListener('pointerdown', e => {
    cur = Object.assign(document.createElement('div'), { className: 'tdot' });
    cur.style.left = e.clientX + 'px'; cur.style.top = e.clientY + 'px';
    document.body.appendChild(cur);
    const d = cur; setTimeout(() => d.classList.add('held'), 30);
  }, true);
  addEventListener('pointerup', () => { const d = cur; if (!d) return; d.classList.add('up'); setTimeout(() => d.remove(), 350); cur = null; }, true);
})();"""


async def main():
    frames_dir = os.path.join(HERE, 'frames')
    shutil.rmtree(frames_dir, ignore_errors=True); os.makedirs(frames_dir)
    frames, timeline, scenes_log = [], [], []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={'width': 1920, 'height': 1080}, color_scheme='light')
        await ctx.add_init_script("try{localStorage.setItem('tutorialSeen','1')}catch(e){}")
        page = await ctx.new_page()
        await page.set_content(SHELL)
        await page.evaluate(f"document.getElementById('kp').src = {json.dumps(URL)}")
        await page.wait_for_function("document.fonts.status === 'loaded'")
        frame = None
        while frame is None:
            await asyncio.sleep(0.1)
            frame = next((f for f in page.frames if f.url.startswith(URL)), None)
        await frame.wait_for_load_state()
        await frame.wait_for_function("document.getElementById('status') && !/Loading/.test(document.getElementById('status').textContent)", timeout=60000)
        await frame.evaluate(TOUCH)
        await frame.evaluate("document.fonts.ready")
        await click(page, frame, '#clear', record=False)
        n = len(SCENES) - 1
        await page.evaluate("n => document.getElementById('dots').innerHTML = Array.from({length: n}, () => '<i></i>').join('')", n)
        await asyncio.sleep(0.5)

        cdp = await ctx.new_cdp_session(page)
        async def on_frame(ev):
            path = os.path.join(frames_dir, f'{len(frames):06d}.jpg')
            open(path, 'wb').write(base64.b64decode(ev['data']))
            frames.append((ev['metadata']['timestamp'], path))
            try: await cdp.send('Page.screencastFrameAck', {'sessionId': ev['sessionId']})
            except Exception: pass
        cdp.on('Page.screencastFrame', lambda ev: asyncio.ensure_future(on_frame(ev)))
        await cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 92, 'maxWidth': 1920, 'maxHeight': 1080})
        await asyncio.sleep(0.5)
        t_start = time.time()

        free_at = 0.0     # when the narration line playing now ends
        for si, (title, steps) in enumerate(SCENES):
            await page.evaluate("([t, i]) => { document.getElementById('title').textContent = t; document.getElementById('cap').textContent = '';"
                                " document.querySelectorAll('#dots i').forEach((d, j) => d.classList.toggle('on', j <= i)); }", [title, si])
            scenes_log.append({'t': time.time(), 'title': title})
            for s in steps:
                kind = s[0]
                if kind == 'say':
                    spoken = s[2] if len(s) > 2 else s[1]
                    await sleep_until(free_at)
                    t = time.time()
                    dur = DURS[spoken]['dur']
                    timeline.append({'t': t, 'file': DURS[spoken]['file'], 'dur': dur, 'text': s[1]})
                    await page.evaluate("t => document.getElementById('cap').textContent = t", s[1])
                    free_at = t + dur + 0.25
                elif kind == 'wait':
                    await sleep_until(free_at)
                elif kind == 'pause':
                    await asyncio.sleep(s[1])
                elif kind == 'clear':
                    await click(page, frame, '#clear')
                    await page.evaluate("document.getElementById('keys').innerHTML = ''")
                    await asyncio.sleep(0.4)
                elif kind == 'keys':
                    await keys(page, frame, s[1])
                elif kind == 'chip':
                    chip = frame.locator('#alts .chip').filter(has_text=re.compile('^' + s[1] + '$')).first
                    await press_box(page, await chip.bounding_box())
                    await add_key(page, s[1], 'tap')
                elif kind == 'send':
                    await click(page, frame, '#copy')
                    await add_key(page, 'Send', 'tap')
            if DRY:
                print(f'{title:30} -> {await frame.locator("#out").inner_text()!r}')
        await sleep_until(free_at)
        await asyncio.sleep(0.6)
        await cdp.send('Page.stopScreencast')
        await asyncio.sleep(0.3)
        await browser.close()
    json.dump({'start': t_start, 'frames': frames, 'scenes': scenes_log}, open(os.path.join(HERE, 'frames.json'), 'w'))
    json.dump(timeline, open(os.path.join(HERE, 'timeline.json'), 'w'), indent=1)
    print(f'{len(frames)} frames, {time.time() - t_start:.1f} s')


async def sleep_until(t):
    d = t - time.time()
    if d > 0: await asyncio.sleep(d)


async def press_box(page, box, hold=False):
    await page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    await page.mouse.down()
    await asyncio.sleep(0.65 if hold else 0.09)
    await page.mouse.up()


async def click(page, frame, sel, record=True):
    await press_box(page, await frame.locator(sel).bounding_box())


async def add_key(page, label, cls=''):
    await page.evaluate("([l, c]) => { const k = document.createElement(l === ' ' ? 'span' : 'kbd');"
                        " if (l === ' ') k.className = 'gap'; else { k.textContent = l; k.className = c; }"
                        " document.getElementById('keys').appendChild(k); }", [label, cls])


async def keys(page, frame, seq):
    groups = seq.split(' ')
    for gi, g in enumerate(groups):
        if gi:
            await add_key(page, ' ')
        i = 0
        while i < len(g):
            hold = g[i] == 'H'
            if hold: i += 1
            k = g[i]; i += 1
            await add_key(page, k, 'hold' if hold else '')
            await press_box(page, await frame.locator(f'[data-key="{k}"]').bounding_box(), hold)
            await asyncio.sleep(0.32 if not hold else 0.45)

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
server = subprocess.Popen([sys.executable, '-m', 'http.server', '8765', '--bind', '127.0.0.1', '--directory', ROOT],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    time.sleep(1)
    asyncio.run(main())
finally:
    server.terminate()
