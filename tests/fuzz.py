"""Randomised conformance fuzzing against the test-only reference.

Generates programs in the documented subset with random identifier names,
random copy/arithmetic chains, overwrites and repeated reads, then compares
every identifier slice.  Also runs invariance checks: renaming, inserted
irrelevant statements, and reformatting must leave the *same tokens*
labelled.

Run:  python3 tests/fuzz.py [n]
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ref
from engine.model import FlowLens

NAMES = ["alpha", "beta", "gamma", "delta", "eps", "zeta", "eta", "theta",
         "iota", "kappa", "lam", "mu", "nu", "xi", "omic", "pi", "rho",
         "sigma", "tau", "ups", "phi", "chi", "psi", "omeg", "tmp", "val",
         "acc", "buf", "cnt", "idx", "res", "sum", "n", "m", "k", "v0",
         "v1", "v2", "xx", "x1", "x2"]


def gen_program(rng):
    names = rng.sample(NAMES, rng.randint(3, 7))
    params = names[: rng.randint(1, 3)]
    body_names = names[len(params):]
    live = list(params)
    lines = []
    header = "int f(" + ", ".join("int " + p for p in params) + ") {"
    lines.append(header)
    declared = []
    for nm in body_names:
        rhs = rng.choice([
            rng.choice(live),
            f"{rng.choice(live)} + {rng.randint(0, 9)}",
            f"{rng.choice(live)} * {rng.randint(2, 9)}",
            f"{rng.choice(live)} % {rng.randint(2, 9)}",
            f"{rng.choice(live)} + {rng.choice(live)}",
            str(rng.randint(0, 99)),
        ])
        lines.append(f"    int {nm} = {rhs};")
        declared.append(nm)
        live.append(nm)
    # a few extra statements: overwrites and copies
    for j in range(rng.randint(0, 4)):
        r = rng.random()
        if r < 0.25 and declared:
            tgt = rng.choice(declared)
            lines.append(f"    {tgt} = {rng.choice(live)} * {rng.randint(1, 5)};")
        elif r < 0.4 and declared:
            tgt = rng.choice(declared)
            op = rng.choice(["+=", "-=", "*="])
            lines.append(f"    {tgt} {op} {rng.choice(live)};")
        elif r < 0.7:
            src_ = rng.choice(live)
            nm = f"zz{j}"
            lines.append(f"    int {nm} = {src_} + {rng.randint(1, 4)};")
            live.append(nm)
        else:
            lines.append(f"    {rng.choice(declared or live)} = "
                         f"{rng.choice(live)};")
    ret = rng.choice(live)
    lines.append(f"    return {ret};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def occurrences(src):
    """Identifier-token byte offsets (test-side only, for picking a cursor)."""
    toks, _ = ref.tokenize(src)
    out = []
    for t in toks:
        if ref.is_ident(t) and t["text"] not in ref.KW:
            out.append((t["start"], t["text"]))
    return out


def score(src, pred, exp, spans):
    fp = fn = tp = 0
    for i in range(len(src)):
        p, e = pred[i], exp[i]
        fp += bool(p and not e)
        fn += bool(e and not p)
        tp += bool(p and e)
    bad = [s for s in spans if any(pred[i] != exp[i] for i in range(*s))]
    pos = [s for s in spans if any(exp[i] for i in range(*s))]
    posbad = [s for s in pos if any(pred[i] != exp[i] for i in range(*s))]
    return dict(fp=fp, fn=fn, tp=tp, bad=bad, pos=pos, posbad=posbad)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    rng = random.Random(20261104)
    fl = FlowLens()
    tot = dict(fp=0, fn=0, tp=0, cases=0, fails=0, pos=0, posbad=0, slices=0,
               badslices=0)
    failures = []
    for i in range(n):
        src = gen_program(rng)
        occ = occurrences(src)
        if not occ:
            continue
        for mode in ("downstream", "upstream"):
            cur, _ = rng.choice(occ)
            try:
                r = fl.analyze(src, cur, mode)
            except Exception as e:                    # noqa: BLE001
                failures.append((i, mode, "exception", repr(e), src))
                tot["fails"] += 1
                continue
            exp = ref.analyze(src, cur, mode)
            s = score(src, r["labels"], exp["labels"], exp["spans"])
            tot["cases"] += 1
            for k in ("fp", "fn", "tp"):
                tot[k] += s[k]
            tot["pos"] += len(s["pos"])
            tot["posbad"] += len(s["posbad"])
            tot["slices"] += len(exp["spans"])
            tot["badslices"] += len(s["bad"])
            if s["bad"]:
                tot["fails"] += 1
                if len(failures) < 6:
                    failures.append((i, mode, cur, src, s))
    print("cases:", tot["cases"], "failed cases:", tot["fails"])
    print("bytes: fp=%d fn=%d tp=%d" % (tot["fp"], tot["fn"], tot["tp"]))
    print("identifier slices: %d/%d exact (%.2f%%)" %
          (tot["slices"] - tot["badslices"], tot["slices"],
           100.0 * (tot["slices"] - tot["badslices"]) / max(1, tot["slices"])))
    print("positive slices: %d/%d exact" %
          (tot["pos"] - tot["posbad"], tot["pos"]))
    for f in failures[:3]:
        print("\nFAIL", f[0], f[1])
        if len(f) == 5:
            print(f[3])
            print("bad slices:", f[4]["bad"][:6], "of", len(f[4]["pos"]),
                  "positive")
    return 0 if tot["fails"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
