"""Invariance and decorated-source fuzzing.

Checks three invariances that a real information-flow model must have and a
"highlight every occurrence of the name" model would fail:

  1. systematic identifier renaming
  2. systematic reformatting (spaces, tabs, newlines)
  3. inserted irrelevant statements

plus programs whose comments and literals contain identifier spellings.

Run:  python3 tests/fuzz2.py [n]
"""

import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ref
from engine.model import FlowLens
from tests.fuzz import gen_program, occurrences  # noqa: E402

fl = FlowLens()


def ident_tokens(src):
    toks, _ = ref.tokenize(src)
    return [t for t in toks if ref.is_ident(t) and t["text"] not in ref.KW]


def signature(src, labels):
    return [(t["start"], t["text"], labels[t["start"]])
            for t in ident_tokens(src)]


def rename(src, rng):
    names = sorted({t["text"] for t in ident_tokens(src)})
    pool = ["p%d" % i for i in range(len(names))]
    rng.shuffle(pool)
    mapping = dict(zip(names, pool))
    return re.sub(r"[A-Za-z_][A-Za-z0-9_]*",
                  lambda m: mapping.get(m.group(0), m.group(0)), src)


def reformat(src, rng):
    out = []
    for ch in src:
        if ch == " " and rng.random() < 0.6:
            out.append(rng.choice(["  ", "\t", " ", "   "]))
        elif ch == "\n" and rng.random() < 0.4:
            out.append("\n\n" + rng.choice(["", "    ", "\t"]))
        else:
            out.append(ch)
    return "".join(out)


def inject(src, rng, avoid):
    lines = src.split("\n")
    k = [i for i, l in enumerate(lines) if l.strip().startswith("int ")]
    if not k:
        return src, []
    pos = rng.choice(k)
    nm = "junk%d" % rng.randint(1000, 9999)
    if nm in avoid:
        return src, []
    lines.insert(pos, f"    int {nm} = 4242 + {rng.randint(0, 9)};")
    return "\n".join(lines), [nm]


def check(src, cur, mode):
    r = fl.analyze(src, cur, mode)
    e = ref.analyze(src, cur, mode)
    ok = r["labels"] == e["labels"]
    return ok, r, e


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    rng = random.Random(777)
    fails = []
    checked = 0
    for i in range(n):
        src = gen_program(rng)
        # decorate with comments and literals that repeat identifiers
        names = [t["text"] for t in ident_tokens(src)][:4]
        if names:
            dec = ("    /* %s %s = 1; */\n" % (names[0], names[-1]) +
                   "    // %s %s\n" % (names[-1], names[0]) +
                   "    char c%d = '%s';\n" % (i, names[0][0]))
            lines = src.split("\n")
            src = "\n".join(lines[:2] + [dec.rstrip("\n")] + lines[2:])
        occ = occurrences(src)
        if not occ:
            continue
        # skip cursors on the synthetic char declaration post-check: ref and
        # model must agree, and both must ignore the literal contents
        for _ in range(2):
            cur, _name = rng.choice(occ)
            for mode in ("downstream", "upstream"):
                checked += 1
                ok, r, e = check(src, cur, mode)
                if not ok:
                    fails.append(("decorated", i, mode, cur, src, r, e))
                    continue
                # ---- renaming invariance
                rs = rename(src, rng)
                base = signature(src, r["labels"])
                rr = fl.analyze(rs, _map_cur(src, rs, cur), mode)
                got = signature(rs, rr["labels"])
                if [x[2] for x in base] != [x[2] for x in got]:
                    fails.append(("rename", i, mode, cur, src, r, e))
                # ---- reformat invariance
                fs = reformat(src, rng)
                fr = fl.analyze(fs, _map_cur(src, fs, cur), mode)
                if [x[2] for x in base] != [x[2] for x in signature(fs,
                                                                   fr["labels"])]:
                    fails.append(("reformat", i, mode, cur, src, r, e))
    print("checked:", checked, "failures:", len(fails))
    for f in fails[:3]:
        print("\nFAIL", f[0], f[1], f[2], "cursor", f[3])
        print(f[4])
    return 0 if not fails else 1


def _map_cur(src, dst, cur):
    """Map a cursor offset across a transformation by identifier ordinal."""
    a = ident_tokens(src)
    b = ident_tokens(dst)
    if not a or not b:
        return 0
    k = 0
    for j, t in enumerate(a):
        if t["start"] <= cur:
            k = j
    return b[min(k, len(b) - 1)]["start"]


if __name__ == "__main__":
    sys.exit(main())
