"""Fresh held-out evaluation with the weights frozen.

Programs here are generated with a different seed and a different shape than
the development and conformance suites (deeper chains, more parameters,
mixed copy/arithmetic/compound statements, comments and literals).  The
expected labels come from tests/ref.py; nothing from this file or from the
reference is visible to the engine.

Run:  python3 tests/holdout_fresh.py [n]
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ref
from engine.model import FlowLens
from tests.fuzz import occurrences  # noqa: E402

POOL = ["seed", "gain", "base", "step", "acc", "hold", "miss", "rate",
        "tone", "wave", "bias", "flux", "core", "edge", "node", "path",
        "unit", "zone", "arch", "beam", "cell", "dock", "echo", "fork"]


def gen(rng):
    names = rng.sample(POOL, rng.randint(4, 9))
    nparam = rng.randint(2, 3)
    params, rest = names[:nparam], names[nparam:]
    live = list(params)
    out = ["int proc(" + ", ".join("int " + p for p in params) + ") {"]
    if rng.random() < 0.35:
        out.append("    /* %s = %s + 1; */" % (params[0], params[-1]))
    for i, nm in enumerate(rest):
        kind = rng.random()
        a, b = rng.choice(live), rng.choice(live)
        if kind < 0.3:
            rhs = a
        elif kind < 0.6:
            rhs = "%s + %s" % (a, b)
        elif kind < 0.8:
            rhs = "%s * %d" % (a, rng.randint(2, 9))
        else:
            rhs = "%s %% %d" % (a, rng.randint(2, 9))
        out.append("    int %s = %s;" % (nm, rhs))
        live.append(nm)
        if rng.random() < 0.3 and i:
            tgt = rng.choice(live[:-1])
            op = rng.choice(["+=", "-=", "*="])
            out.append("    %s %s %s;" % (tgt, op, rng.choice(live)))
    if rng.random() < 0.3:
        out.append("    char mark = '%s';" % params[0][0])
    out.append("    return %s;" % rng.choice(live))
    out.append("}")
    src = "\n".join(out) + "\n"
    if rng.random() < 0.3:                      # reformat
        src = src.replace("    ", "\t").replace(" = ", "=")
    return src


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    rng = random.Random(20261105)               # not used during development
    fl = FlowLens()
    tot = dict(cases=0, fp=0, fn=0, tp=0, pos=0, posbad=0, slices=0,
               badslices=0, fails=0)
    fail_examples = []
    for i in range(n):
        src = gen(rng)
        occ = occurrences(src)
        if not occ:
            continue
        for mode in ("downstream", "upstream"):
            cur = rng.choice(occ)[0]
            r = fl.analyze(src, cur, mode)
            e = ref.analyze(src, cur, mode)
            fp = fn = tp = 0
            for k in range(len(src)):
                p, x = r["labels"][k], e["labels"][k]
                fp += bool(p and not x)
                fn += bool(x and not p)
                tp += bool(p and x)
            bad = [s for s in e["spans"]
                   if any(r["labels"][k] != e["labels"][k] for k in range(*s))]
            pos = [s for s in e["spans"] if any(e["labels"][k] for k in range(*s))]
            posbad = [s for s in pos
                      if any(r["labels"][k] != e["labels"][k] for k in range(*s))]
            tot["cases"] += 1
            tot["fp"] += fp
            tot["fn"] += fn
            tot["tp"] += tp
            tot["slices"] += len(e["spans"])
            tot["badslices"] += len(bad)
            tot["pos"] += len(pos)
            tot["posbad"] += len(posbad)
            if bad or fp or fn:
                tot["fails"] += 1
                if len(fail_examples) < 3:
                    fail_examples.append((src, cur, mode, bad[:4]))
    print("held-out cases: %d   failing: %d" % (tot["cases"], tot["fails"]))
    print("bytes: fp=%d fn=%d tp=%d" % (tot["fp"], tot["fn"], tot["tp"]))
    print("identifier slices exact: %d/%d (%.2f%%)" %
          (tot["slices"] - tot["badslices"], tot["slices"],
           100.0 * (tot["slices"] - tot["badslices"]) / max(1, tot["slices"])))
    print("positive slices exact:   %d/%d (%.2f%%)" %
          (tot["pos"] - tot["posbad"], tot["pos"],
           100.0 * (tot["pos"] - tot["posbad"]) / max(1, tot["pos"])))
    for ex in fail_examples:
        print("\nFAIL cursor=%d mode=%s slices=%s" % (ex[1], ex[2], ex[3]))
        print(ex[0])
    return 0 if tot["fails"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
