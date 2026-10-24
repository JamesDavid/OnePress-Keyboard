"""Export the neural word model (train_nn.py) to KPN1, the file the decoders read.

Usage: python export_nn.py nn.pt model.json onepress-nn.bin [--weight 1.0]

Everything is integer so the C and JS decoders agree exactly: int8 weights with power-of-two
scales, a hidden state in Q12 (value * 4096), and a sigmoid table stored in the file.

Header (32 bytes, little-endian):
  "KPN1", u16 version (1), u16 E (embedding), u16 H (hidden), u16 V (tokens),
  u16 bos, u16 unk, i16 weight (in 1/256: how much the neural score counts),
  u8 se, u8 sih, u8 shh, u8 sp (scale shifts), u32 reserved, u16 model bos (the KPD2 model's),
  u16 reserved, u16 reserved
then, 4-byte aligned in this order:
  sig   i16[4096]  sigmoid, Q12, of (i * 16 - 32768) / 4096  (x in [-8, 8))
  emb   i8[V][E]   token embeddings, value * 2^se (shared by input and output)
  wih   i8[3H][E]  GRU input weights (r, z, n), value * 2^sih
  whh   i8[3H][H]  GRU hidden weights, value * 2^shh
  bih   i32[3H]    Q12
  bhh   i32[3H]    Q12
  proj  i8[E][H]   hidden -> embedding space, value * 2^sp
  bproj i32[E]     Q12
  bias  i16[V]     output bias, in 1/256 nat

One step for token t from state h (Q12), all shifts arithmetic (floor):
  x = emb[t];  gi = (wih . x) >> (sih + se - 12);  gh = (whh . h) >> shh   (per gate row)
  r = SIG(gi_r + bih_r + gh_r + bhh_r);  z = SIG(gi_z + bih_z + gh_z + bhh_z)
  n = TANH(gi_n + bih_n + ((r * (gh_n + bhh_n)) >> 12))
  h' = ((4096 - z) * n + z * h) >> 12
  SIG(v) = sig[(clamp(v, -32768, 32767) + 32768) >> 4];  TANH(v) = 2 * SIG(2 v) - 4096
Score of token w after state h, in 1/256 nat (log P, the softmax being trained to normalize to ~1):
  p = clamp(((proj . h) >> sp) + bproj, -32767, 32767);  score = ((p . emb[w]) >> (se + 4)) + bias[w]
"""
import argparse, json, math, struct
import numpy as np
import torch

def shift_for(t, bits=7):
    m = float(np.abs(t).max())
    return max(0, int(math.floor(math.log2((2 ** bits - 1) / m)))) if m > 0 else 0

def q8(t, s):
    return np.clip(np.round(t * 2 ** s), -127, 127).astype(np.int8)

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

    emb, wih, whh = st["emb.weight"], st["gru.weight_ih_l0"], st["gru.weight_hh_l0"]
    se, sih, shh, sp = shift_for(emb), shift_for(wih), shift_for(whh), shift_for(st["proj.weight"])
    assert sih + se >= 12, (sih, se)
    sig = np.round(4096 / (1 + np.exp(-((np.arange(4096) * 16 - 32768 + 8) / 4096)))).astype(np.int16)
    sec = [
        sig.tobytes(),
        q8(emb, se).tobytes(),
        q8(wih, sih).tobytes(),
        q8(whh, shh).tobytes(),
        np.round(st["gru.bias_ih_l0"] * 4096).astype(np.int32).tobytes(),
        np.round(st["gru.bias_hh_l0"] * 4096).astype(np.int32).tobytes(),
        q8(st["proj.weight"], sp).tobytes(),
        np.round(st["proj.bias"] * 4096).astype(np.int32).tobytes(),
        np.clip(np.round(st["bias"] * 256), -32768, 32767).astype(np.int16).tobytes(),
    ]
    head = b"KPN1" + struct.pack("<HHHHHHhBBBBIHHH", 1, E, H, V, ck["BOS"], ck["UNK"], round(a.weight * 256),
                                 se, sih, shh, sp, 0, M["bos"], 0, 0)
    assert len(head) == 32
    body = b""
    for s in sec:
        body += b"\0" * (-(len(head) + len(body)) % 4) + s
    open(a.out, "wb").write(head + body)
    print(f"KPN1: E {E}, H {H}, V {V}, shifts se {se} sih {sih} shh {shh} sp {sp}, {len(head) + len(body):,} bytes")

if __name__ == "__main__":
    main()
