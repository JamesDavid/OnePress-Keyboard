# Speaks each narration line of scenes.py into build/video/clips (Kokoro, run locally) and writes
# clips/durations.json. Usage: python tts.py [voice]
import hashlib, json, os, sys
import soundfile as sf
from kokoro_onnx import Kokoro
import scenes

HERE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'build', 'video'))   # work files
voice = sys.argv[1] if len(sys.argv) > 1 else 'af_heart'
k = Kokoro(os.path.join(HERE, 'kokoro', 'kokoro-v1.0.onnx'), os.path.join(HERE, 'kokoro', 'voices-v1.0.bin'))
lines = scenes.lines()
os.makedirs(os.path.join(HERE, 'clips'), exist_ok=True)
durs = {}
for line in lines:
    spoken = line['say']     # how it's spoken; line['text'] is the caption
    h = hashlib.sha1((voice + spoken).encode()).hexdigest()[:12]
    path = os.path.join(HERE, 'clips', h + '.wav')
    if not os.path.exists(path):
        samples, rate = k.create(spoken, voice=voice, speed=1.0, lang='en-us')
        sf.write(path, samples, rate)
    info = sf.info(path)
    durs[spoken] = {'file': path, 'dur': info.frames / info.samplerate}
    print(f'{durs[spoken]["dur"]:5.2f}s  {spoken}')
json.dump(durs, open(os.path.join(HERE, 'clips', 'durations.json'), 'w', encoding='utf-8'), indent=1)
