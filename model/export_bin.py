import json, struct, sys
M = json.load(open(sys.argv[1])); out = sys.argv[2]
words = M["words"]; n = len(words); P = M["punct"]; bos = M["bos"]
assert bos == n + len(P)
rows = bos + 1
offs = [0] * (rows + 1); nxt = []; cnt = []
bi = {int(k): v for k, v in M["bi"].items()}
for r in range(rows):
    arr = bi.get(r, [])
    pairs = sorted(zip(arr[0::2], arr[1::2]))
    for a, c in pairs: nxt.append(a); cnt.append(c)
    offs[r + 1] = len(nxt)
b = bytearray(b"KPD1")
b += struct.pack("<III", n, len(P), bos)
wb = "\n".join(words).encode(); b += struct.pack("<I", len(wb)) + wb
disp = M.get("display", {})
b += struct.pack("<I", len(disp))
for k, v in sorted(disp.items(), key=lambda kv: int(kv[0])):
    vb = v.encode(); b += struct.pack("<II", int(k), len(vb)) + vb
b += struct.pack(f"<{n}f", *M["logp"])
b += struct.pack(f"<{len(P)}f", *M["punctLogp"])
b += "".join(P).encode()
b += struct.pack("<I", rows) + struct.pack(f"<{rows+1}I", *offs)
b += struct.pack("<I", len(nxt)) + struct.pack(f"<{len(nxt)}I", *nxt) + struct.pack(f"<{len(cnt)}I", *cnt)
open(out, "wb").write(b)
# round-trip check of ctx sums
ctx = {int(k): v for k, v in M["ctx"].items()}
for r in range(rows):
    s = sum(cnt[offs[r]:offs[r+1]])
    assert s == ctx.get(r, 0), (r, s, ctx.get(r))
print("rows", rows, "entries", len(nxt), "bytes", len(b))
