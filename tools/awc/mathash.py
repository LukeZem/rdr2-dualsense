"""Which hash turns a material name into the hash GET_GROUND_Z_AND_MATERIAL returns?
Known pairs from GTA V (ScriptHookVDotNet MaterialHash.cs): DEFAULT -> 0x962C3F7B, CONCRETE -> 0x46CA81E8..."""
import sys
import zlib

F = 0xFFFFFFFF


def oaat(b, seed=0, fin=True):
    h = seed
    for c in b:
        h = (h + c) & F
        h = (h + (h << 10)) & F
        h ^= h >> 6
    if fin:
        h = (h + (h << 3)) & F
        h ^= h >> 11
        h = (h + (h << 15)) & F
    return h


def fnv1(b):
    h = 0x811C9DC5
    for c in b:
        h = (h * 0x01000193) & F
        h ^= c
    return h


def fnv1a(b):
    h = 0x811C9DC5
    for c in b:
        h ^= c
        h = (h * 0x01000193) & F
    return h


PAIRS = {"DEFAULT": 0x962C3F7B, "CONCRETE": 0x46CA81E8, "TARMAC": 0x10DD5498, "ROCK": 0xCDEB5023, "STONE": 0x2D9C1E0D}
FUNCS = {"oaat": oaat, "crc32": lambda b: zlib.crc32(b) & F, "fnv1": fnv1, "fnv1a": fnv1a,
         "crc32inv": lambda b: (~zlib.crc32(b)) & F, "oaat_nofin": lambda b: oaat(b, fin=False)}

if __name__ == "__main__":
    hits = 0
    prefixes = ["", "materials", "material", "mtl", "MTL", "phMaterial", "phmaterial", "mat", "MAT", "surface",
                "common:/data/materials/", "platform:/data/materials/"]
    seps = ["", "_", "/", ":", ".", "\\", " "]
    suffixes = ["", "\0", "_MTL", "_mtl", ".mtl", "_0", "0"]
    for name, target in PAIRS.items():
        for nn in {name, name.lower(), name.capitalize()}:
            for pre in prefixes:
                for sep in seps if pre else [""]:
                    for suf in suffixes:
                        s = (pre + sep + nn + suf).encode()
                        for fn, fun in FUNCS.items():
                            if fun(s) == target or fun(s.lower()) == target:
                                print("HIT", name, repr(s), fn)
                                hits += 1
    # joaat seeded with an arbitrary value: solve for "DEFAULT" against all 2^32 seeds is too slow in Python,
    # but a seed shared by all pairs can be checked cheaply on candidates from the first pair's prefix list
    print("hits:", hits)
    sys.exit(0)
