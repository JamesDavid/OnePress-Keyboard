# Builds the MP4 from frames.json (screencast frames) and timeline.json (narration starts), plus an SRT.
import json, os, subprocess, sys
HERE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'build', 'video'))   # work files
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'onepress-keypad-tutorial.mp4')
d = json.load(open(os.path.join(HERE, 'frames.json')))
tl = json.load(open(os.path.join(HERE, 'timeline.json')))
t0 = d['frames'][0][0]
frames = d['frames']
end = max(frames[-1][0], max(x['t'] + x['dur'] for x in tl) + 0.8)

lst = os.path.join(HERE, 'frames.txt')
with open(lst, 'w') as f:
    for i, (t, p) in enumerate(frames):
        nxt = frames[i + 1][0] if i + 1 < len(frames) else end
        f.write(f"file '{p.replace(os.sep, '/')}'\nduration {max(nxt - t, 0.001):.4f}\n")
    f.write(f"file '{frames[-1][1].replace(os.sep, '/')}'\n")

inputs, filters = [], []
for i, x in enumerate(tl):
    inputs += ['-i', x['file']]
    ms = int((x['t'] - t0) * 1000)
    filters.append(f'[{i + 1}:a]aresample=48000,adelay={ms}|{ms}[a{i}]')
mix = ''.join(f'[a{i}]' for i in range(len(tl))) + f'amix=inputs={len(tl)}:normalize=0,apad,atrim=0:{end - t0:.3f}[aout]'
dur = end - t0
vf = f'[0:v]fps=30,format=yuv420p,fade=t=in:st=0:d=0.5,fade=t=out:st={dur - 0.7:.2f}:d=0.7[vout]'
cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst] + inputs + [
    '-filter_complex', ';'.join(filters + [mix, vf]), '-map', '[vout]', '-map', '[aout]',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-tune', 'stillimage', '-c:a', 'aac', '-b:a', '160k',
    '-movflags', '+faststart', '-t', f'{dur:.3f}', out]
subprocess.run(cmd, check=True)

def ts(s):
    ms = int(round(s * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); sec, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{sec:02},{ms:03}'
with open(os.path.splitext(out)[0] + '.srt', 'w', encoding='utf-8') as f:
    for i, x in enumerate(tl):
        f.write(f"{i + 1}\n{ts(x['t'] - t0)} --> {ts(x['t'] - t0 + x['dur'])}\n{x['text']}\n\n")
print(f'{out}: {dur:.1f} s')
