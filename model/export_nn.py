"""Export the neural word model (train_nn.py) to KPN1, the file the decoders read.

Usage: python export_nn.py nn.pt model.json onepress-nn.bin [--weight 1.0]

Everything is integer so the C and JS decoders agree exactly: int8 weights with a power-of-two
scale per row (value = q / 2^shift), a hidden state in Q12 (value * 4096), and a sigmoid table
stored in the file.

Header (32 bytes, little-endian):
  "KPN1", u16 version (1), u16 E (embedding), u16 H (hidden), u16 V (tokens),
  u16 bos, u16 unk, i16 weight (in 1/256: how much the neural score counts),
  u8[4] reserved, u32 reserved, u16 model bos (the KPD2 model's), u16 reserved, u16 reserved
then, each 4-byte aligned, in this order:
  sig   i16[4096]   sigmoid, Q12, of (i * 16 - 32768 + 8) / 4096  (x in [-8, 8))
  emb   i8[V][E]    token embeddings (shared by input and output), es[V] u8 row shifts
  wih   i8[3H][E]   GRU input weights (rows r, z, n), is[3H] u8 row shifts
  whh   i8[3H][H]   GRU hidden weights, hs[3H] u8 row shifts
  bih   i32[3H]     Q12
  bhh   i32[3H]     Q12
  proj  i8[E][H]    hidden -> embedding space, ps[E] u8 row shifts
  bproj i32[E]      Q12
  bias  i16[V]      output bias, in 1/256 nat
(each u8 shift array follows its matrix, padded to 4 bytes)

One step for token t from state h (Q12), all shifts arithmetic (floor):
  Q(a, s) = s >= 12 ? a >> (s - 12) : a * 2^(12 - s)        (a scaled by 2^s -> Q12)
  gi_k = Q(wih[k] . emb[t], is[k] + es[t]);  gh_k = (whh[k] . h) >> hs[k]
  each clamped to +-524287
  r = SIG(gi_r + bih_r + gh_r + bhh_r);  z = SIG(gi_z + bih_z + gh_z + bhh_z)
  n = TANH(gi_n + bih_n + ((r * (gh_n + bhh_n)) >> 12))
  h' = ((4096 - z) * n + z * h) >> 12
  SIG(v) = sig[(clamp(v, -32768, 32767) + 32768) >> 4];  TANH(v) = 2 * SIG(2 v) - 4096
Score of token w after state h, in 1/256 nat (log P; the softmax was trained to sum to ~1):
  p_e = clamp(((proj[e] . h) >> ps[e]) + bproj_e, +-32767)
  score = clamp(((p . emb[w]) >> (es[w] + 4)) + bias[w], +-32767)
"""
import argparse, json, math, struct
import numpy as np
import torch

def rows(m):
    """int8 rows and the shift of each: the largest that keeps the row's values within 127."""
    mx = np.abs(m).max(1)
    sh = np.clip(np.floor(np.log2(127 / np.maximum(mx, 1e-9))), 0, 30).astype(np.uint8)
    q = np.clip(np.round(m * (2.0 ** sh[:, None])), -127, 127).astype(np.int8)
    return q, sh

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("nn_pt")
    ap.add_argument("model_json")
    ap.add_argument("out")
    ap.add_argument("--weight", type=float, default=1.0)
    a = ap.parse_args()
    ck = torch.load(a.nn_pt, map_location="cpu")
    st = {k: v.float().numpy() for k, v in ck["state"].items()}
    E, H, V = ck["embed"], ck["hidden"], ck["V"]
    M = json.load(open(a.model_json, encoding="utf-8"))
    assert ck["BOS"] == M["bos"], "the network was trained on another vocabulary"
    assert E <= 256 and H <= 256

    sig = np.round(4096 / (1 + np.exp(-((np.arange(4096) * 16 - 32768 + 8) / 4096)))).astype(np.int16)
    emb, es = rows(st["emb.weight"])
    wih, is_ = rows(st["gru.weight_ih_l0"])
    whh, hs = rows(st["gru.weight_hh_l0"])
    proj, ps = rows(st["proj.weight"])
    sec = [
        sig.tobytes(),
        emb.tobytes(), es.tobytes(),
        wih.tobytes(), is_.tobytes(),
        whh.tobytes(), hs.tobytes(),
        np.round(st["gru.bias_ih_l0"] * 4096).astype(np.int32).tobytes(),
        np.round(st["gru.bias_hh_l0"] * 4096).astype(np.int32).tobytes(),
        proj.tobytes(), ps.tobytes(),
        np.round(st["proj.bias"] * 4096).astype(np.int32).tobytes(),
        np.clip(np.round(st["bias"] * 256), -32767, 32767).astype(np.int16).tobytes(),
    ]
    head = b"KPN1" + struct.pack("<HHHHHHhBBBBIHHH", 1, E, H, V, ck["BOS"], ck["UNK"], round(a.weight * 256),
                                 0, 0, 0, 0, 0, M["bos"], 0, 0)
    assert len(head) == 32
    body = b""
    for s in sec:
        body += b"\0" * (-(len(head) + len(body)) % 4) + s
    open(a.out, "wb").write(head + body)
    print(f"KPN1: E {E}, H {H}, V {V}, {len(head) + len(body):,} bytes")

if __name__ == "__main__":
    main()
