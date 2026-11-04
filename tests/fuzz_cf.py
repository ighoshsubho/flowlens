"""Randomised control-flow conformance against the reference.

Generates programs with nested braced if / else / while bodies, random copy
and arithmetic chains, overwrites inside and outside blocks, then compares
every identifier occurrence in both modes.

This is the gate for the v2 block machinery (merge nodes, loop-carried
dependence).  Run:  python3 tests/fuzz_cf.py [n]
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ref
from engine.model import FlowLens

NAMES = ["alpha", "beta", "gamma", "delta", "eps", "zeta", "eta", "theta",
         "iota", "kappa", "lam", "mu", "nu", "xi", "rho", "tau", "phi",
         "chi", "psi", "omeg", "tmp", "val", "acc", "buf", "cnt", "idx",
         "res", "sum", "n0", "n1", "v0", "v1", "x1", "x2", "xx"]


def gen(rng):
    names = rng.sample(NAMES, 8)
    params = names[:2]
    live = list(params)
    body = []
    decls = names[2:6]
    for nm in decls:
        live.append(nm)

    def expr():
        r = rng.random()
        a = rng.choice(live)
        b = rng.choice(live)
        if r < 0.4:
            return a
        if r < 0.7:
            return "%s + %s" % (a, b)
        return "%s * %d" % (a, rng.randint(2, 9))

    for nm in decls:
        body.append("    int %s = %s;" % (nm, expr()))

    loop_id = [0]

    def single(depth):
        """One statement, for a body written without braces."""
        ind = "    " * (depth + 2)
        return ind + "%s = %s;" % (rng.choice(live), expr())

    def stmts(depth, k):
        out = []
        ind = "    " * (depth + 1)
        for _ in range(k):
            r = rng.random()
            if r < 0.30:
                out.append(ind + "%s = %s;" % (rng.choice(live), expr()))
            elif r < 0.40 and depth < 2:
                out.append(ind + "int %s = %s;"
                           % (rng.choice(["aa", "bb", "cc", "dd"]), expr()))
            elif r < 0.52 and depth < 2:
                out.append(ind + "if (%s) {" % rng.choice(params))
                out.extend(stmts(depth + 1, 2))
                if rng.random() < 0.5:
                    out.append(ind + "} else {")
                    out.extend(stmts(depth + 1, 2))
                out.append(ind + "}")
            elif r < 0.58 and depth < 2:                 # unbraced if
                out.append(ind + "if (%s)" % rng.choice(params))
                out.append(single(depth))
                if rng.random() < 0.5:
                    out.append(ind + "else")
                    out.append(single(depth))
            elif r < 0.66 and depth < 2:
                out.append(ind + "while (%s) {" % rng.choice(live))
                out.extend(stmts(depth + 1, 2))
                out.append(ind + "}")
            elif r < 0.70 and depth < 2:                 # unbraced while
                out.append(ind + "while (%s)" % rng.choice(live))
                out.append(single(depth))
            elif r < 0.82 and depth < 2:                 # braced for
                loop_id[0] += 1
                iv = "iv%d" % loop_id[0]
                out.append(ind + "for (int %s = 0; %s < %s; %s++) {"
                           % (iv, iv, rng.choice(params), iv))
                out.extend(stmts(depth + 1, 2))
                out.append(ind + "}")
            elif r < 0.88 and depth < 2:                 # for, single body
                loop_id[0] += 1
                iv = "iv%d" % loop_id[0]
                st = rng.choice(["%s++" % iv, "%s = %s + 1" % (iv, iv),
                                 "%s += 1" % iv])
                out.append(ind + "for (int %s = 0; %s < %s; %s)"
                           % (iv, iv, rng.choice(params), st))
                out.append(single(depth))
            elif r < 0.95 and depth < 2:                 # braced do/while
                out.append(ind + "do {")
                out.extend(stmts(depth + 1, 2))
                out.append(ind + "} while (%s);" % rng.choice(live))
            elif depth < 2:                              # do, single body
                out.append(ind + "do")
                out.append(single(depth))
                out.append(ind + "while (%s);" % rng.choice(live))
        return out

    body.extend(stmts(0, rng.randint(1, 3)))
    body.append("    return %s;" % rng.choice(live))
    src = ("int work(" + ", ".join("int " + p for p in params) + ") {\n"
           + "\n".join(body) + "\n}\n")
    return src


def occurrences(src):
    toks, _ = ref.tokenize(src)
    return [t["start"] for t in toks
            if ref.is_ident(t) and t["text"] not in ref.KW]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    rng = random.Random(4242)
    fl = FlowLens()
    tot = dict(cases=0, fails=0, fp=0, fn=0, slices=0, badslices=0)
    examples = []
    for p in range(n):
        src = gen(rng)
        occ = occurrences(src)
        if not occ:
            continue
        for cur in occ:
            for mode in ("downstream", "upstream"):
                try:
                    m = fl.analyze(src, cur, mode)
                except Exception as e:                    # noqa: BLE001
                    tot["fails"] += 1
                    examples.append((src, cur, mode, "exception " + repr(e)))
                    continue
                e = ref.analyze(src, cur, mode)
                tot["cases"] += 1
                fp = fn = 0
                for k in range(len(src)):
                    a, b = m["labels"][k], e["labels"][k]
                    fp += bool(a and not b)
                    fn += bool(b and not a)
                bad = [s for s in e["spans"]
                       if any(m["labels"][k] != e["labels"][k]
                              for k in range(*s))]
                tot["fp"] += fp
                tot["fn"] += fn
                tot["slices"] += len(e["spans"])
                tot["badslices"] += len(bad)
                if bad or fp or fn:
                    tot["fails"] += 1
                    if len(examples) < 3:
                        examples.append((src, cur, mode,
                                         "bad=%d fp=%d fn=%d"
                                         % (len(bad), fp, fn)))
    print("cases: %d   failing: %d" % (tot["cases"], tot["fails"]))
    print("bytes: fp=%d fn=%d" % (tot["fp"], tot["fn"]))
    print("identifier slices exact: %d/%d (%.2f%%)" %
          (tot["slices"] - tot["badslices"], tot["slices"],
           100.0 * (tot["slices"] - tot["badslices"]) / max(1, tot["slices"])))
    for ex in examples:
        print("\nFAIL cursor=%d mode=%s %s" % (ex[1], ex[2], ex[3]))
        print(ex[0])
    return 0 if tot["fails"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
