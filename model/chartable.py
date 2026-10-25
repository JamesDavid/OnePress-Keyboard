"""The letters beyond a-z that the decoders know: for each code point of Latin-1 / Latin
Extended-A and -B (U+00C0-U+024F), Greek (U+0370-U+03FF) and Cyrillic (U+0400-U+045F), its keypad
key, the plain letter it matches when typed exactly or tapped on QWERTY (Latin letters only),
its capital, and its small letter (to lowercase the text before the cursor the same way in C).

    python model/chartable.py        rewrites the generated tables in web/decoder.js and
                                     c/onepress.c (between their CHARTABLE markers)

export_bin.py imports key_of() from here, so the models' key indexes agree with the decoders.

Keys: Latin letters take their plain letter's key (á -> 2, ł -> 5, ş -> 7). Greek and Cyrillic
use the usual phone layouts: Greek 2 αβγ 3 δεζ 4 ηθι 5 κλμ 6 νξο 7 πρσς 8 τυφ 9 χψω; Russian
2 абвг 3 деёжз 4 ийкл 5 мноп 6 рсту 7 фхцч 8 шщъы 9 ьэюя (Ukrainian і ї go with и, є with е,
ґ with г). Accented Greek letters take their plain letter's key.
"""
import os, re, unicodedata

RANGES = [(0x00C0, 0x0250), (0x0370, 0x0400), (0x0400, 0x0460)]
LATIN_KEYS = {c: k for k, letters in {"2": "abc", "3": "def", "4": "ghi", "5": "jkl", "6": "mno",
              "7": "pqrs", "8": "tuv", "9": "wxyz"}.items() for c in letters}
# Latin letters with no decomposition to a plain letter.
LATIN_EXTRA = {"æ": "a", "ð": "d", "ø": "o", "þ": "t", "ß": "s", "đ": "d", "ħ": "h", "ı": "i", "ĳ": "i",
               "ĸ": "k", "ŀ": "l", "ł": "l", "ŉ": "n", "ŋ": "n", "œ": "o", "ŧ": "t", "ſ": "s", "ƀ": "b",
               "ƃ": "b", "ƈ": "c", "ƌ": "d", "ƒ": "f", "ƙ": "k", "ƚ": "l", "ƞ": "n", "ƥ": "p", "ƫ": "t",
               "ƭ": "t", "ƴ": "y", "ƶ": "z", "ǥ": "g", "ȥ": "z", "ȿ": "s", "ɀ": "z", "ɇ": "e", "ɉ": "j",
               "ɋ": "q", "ɍ": "r", "ɏ": "y"}
GREEK = dict(zip("αβγδεζηθικλμνξοπρσςτυφχψω", "2223334445556667777888999"))
CYRILLIC = {c: k for k, letters in {"2": "абвгґ", "3": "деёжзє", "4": "ийклії", "5": "мноп", "6": "рсту",
            "7": "фхцч", "8": "шщъы", "9": "ьэюя"}.items() for c in letters}

def lower_of(cp):
    """Small letter of code point cp (itself if none, or not a single letter in the ranges)."""
    low = chr(cp).lower()
    return ord(low) if len(low) == 1 and chr(cp).isupper() and -128 <= ord(low) - cp <= 127 else cp

def entry(cp):
    """(key, plain letter, capital code point) of code point cp; key '' if it isn't a letter."""
    c = chr(cp)
    if not c.isalpha():
        return "", "", cp
    low = c.lower()
    if len(low) != 1:
        low = c
    up = c.upper()
    upper = ord(up) if len(up) == 1 and c.islower() else cp
    base = unicodedata.normalize("NFD", low)[0]
    if "a" <= base <= "z":
        return LATIN_KEYS[base], base, upper
    if low in LATIN_EXTRA:
        return LATIN_KEYS[LATIN_EXTRA[low]], LATIN_EXTRA[low], upper
    if base in GREEK:
        return GREEK[base], "", upper
    if low in CYRILLIC or base in CYRILLIC:
        return CYRILLIC.get(low) or CYRILLIC[base], "", upper
    return "", "", cp

def key_of(c):
    """Keypad key of a letter of a model's word ('' if the decoders don't know it)."""
    if "a" <= c <= "z":
        return LATIN_KEYS[c]
    if c == "'":
        return "#"
    for lo, hi in RANGES:
        if lo <= ord(c) < hi:
            return entry(ord(c))[0]
    return ""

def tables():
    """Per range: keys ('0' = not a letter), plain letters ('0' = none), capital and small offsets."""
    out = []
    for lo, hi in RANGES:
        keys, base, delta, ldelta = "", "", [], []
        for cp in range(lo, hi):
            k, b, up = entry(cp)
            keys += k or "0"
            base += b or "0"
            d = up - cp if k else 0
            if not -128 <= d <= 127:
                d = 0                   # (ı -> I): rare at a sentence start, left as it is
            delta.append(d)
            ldelta.append(lower_of(cp) - cp if k else 0)
        out.append((lo, hi, keys, base, delta, ldelta))
    return out

def js():
    rows = []
    for lo, hi, keys, base, delta, ldelta in tables():
        rows.append(f"  [0x{lo:04x}, '{keys}',\n   '{base}',\n   [{','.join(map(str, delta))}],\n   [{','.join(map(str, ldelta))}]],")
    return "const CHARTABLE = [   // [first code point, keys, plain letters, capital offsets, small offsets]\n" + "\n".join(rows) + "\n];"

def c():
    lines = ["static const struct { uint16_t lo, hi; const char *keys, *base; const signed char *delta, *ldelta; } CHARTABLE[] = {"]
    decl = []
    for n, (lo, hi, keys, base, delta, ldelta) in enumerate(tables()):
        decl.append(f"static const signed char CT_DELTA{n}[] = {{{','.join(map(str, delta))}}};")
        decl.append(f"static const signed char CT_LDELTA{n}[] = {{{','.join(map(str, ldelta))}}};")
        lines.append(f'    {{ 0x{lo:04X}, 0x{hi:04X},\n      "{keys}",\n      "{base}", CT_DELTA{n}, CT_LDELTA{n} }},')
    return "\n".join(decl) + "\n" + "\n".join(lines) + "\n};"

def replace(path, text):
    s = open(path, encoding="utf-8").read()
    a, b = "CHARTABLE generated by model/chartable.py: begin", "CHARTABLE generated by model/chartable.py: end"
    i, j = s.index(a), s.index(b)
    i = s.index("\n", i) + 1
    j = s.rindex("\n", 0, j) + 1
    open(path, "w", encoding="utf-8", newline="\n").write(s[:i] + text + "\n" + s[j:])

if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    replace(os.path.join(root, "web", "decoder.js"), js())
    replace(os.path.join(root, "c", "onepress.c"), c())
    print("tables:", [(hex(lo), hi - lo) for lo, hi, *_ in tables()])
