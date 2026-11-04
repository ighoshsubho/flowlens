"""Development and held-out evaluation for FlowLens.

Each case is a source string with a '|' marker giving the cursor, plus a
mode.  Expected labels come from tests/ref.py (test-only).  Metrics are
reported per identifier slice, not just per byte, so a model that labels
nothing cannot look good.

Run:  python3 tests/evaluate.py
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ref
from engine.model import FlowLens, Unsupported

DEV = []
HOLD = []


def case(name, text, mode="downstream"):
    cur = text.index("|")
    src = text.replace("|", "", 1)
    return dict(name=name, src=src, cursor=cur, mode=mode)


# ---------------------------------------------------------------------------
# Development suite
# ---------------------------------------------------------------------------
DEV += [
    case("basic-copy", """int demo(int input, int ignored) {
    int x = input + 1;
    int saved = |x;
    x = 0;
    int unrelated = ignored * 2;
    int result = saved * 3;
    return result;
}
"""),
    case("copy-chain", """int f(int p) {
    int a = p + 1;
    int b = |a;
    int c = b;
    int d = c * 2;
    return d;
}
"""),
    case("arith-two-inputs", """int f(int m, int n) {
    int s = m + n;
    int t = |s * 2;
    return t;
}
"""),
    case("independent", """int f(int a, int b) {
    int u = |a * 3;
    int v = b + 7;
    return v;
}
"""),
    case("overwritten", """int f(int a) {
    int y = a + 1;
    int keep = |y;
    y = 9;
    y = y + 1;
    return keep;
}
"""),
    case("repeated-reads", """int f(int a) {
    int z = |a + 1;
    int q = z + z;
    int r = q * z;
    return r + z;
}
"""),
    case("prefix-names", """int f(int aa, int aab) {
    int a = aa + 1;
    int ab = |a * 2;
    int aab2 = aab + ab;
    return aab2;
}
"""),
    case("comment-noise", """int f(int v) {
    // v is not read here: v v v
    int w = |v + 1;
    /* w = 99; */
    int z = w * 2;
    return z;
}
"""),
    case("string-noise", """int f(int v) {
    char c = 'v';
    int w = |v + 1;
    int z = w + 2;
    return z;
}
"""),
    case("formatting", """int f(int v)
{
	int w = |v+1;

	int z=w  *  2;
	return z ;
}
"""),
    case("if-merge", """int f(int a, int c) {
    int s = a;
    if (c) {
        s = 5;
    }
    return |s;
}
"""),
    case("if-else-merge", """int f(int a, int c) {
    int s = a;
    if (c) {
        s = 5;
    } else {
        s = 7;
    }
    return |s;
}
"""),
    case("while-keeps-old", """int z(int a, int c) {
    int s = a;
    while (c) {
        s = 5;
    }
    return |s;
}
"""),
    case("while-carried", """int f(int a) {
    int s = 0;
    int i = 0;
    while (i < 3) {
        s = s + a;
        i = i + 1;
    }
    return |s;
}
""", "upstream"),
    case("while-carried-down", """int f(int a) {
    int s = 0;
    int i = 0;
    while (i < 3) {
        s = |s + a;
        i = i + 1;
    }
    return s;
}
"""),
    case("nested-if", """int f(int a, int c, int d) {
    int s = a;
    if (c) {
        if (d) {
            s = 1;
        }
        s = s + 2;
    }
    return |s;
}
"""),
    case("multi-declarator", """int f(int a) {
    int p = a + 1, q = |p * 2, r = q + 3;
    return r;
}
"""),
    case("decl-no-init", """int f(int a) {
    int tmp;
    int b = |a + 1;
    tmp = b * 2;
    return tmp;
}
"""),
    case("upstream-return", """int f(int a) {
    int b = a + 1;
    int c = b * 2;
    return |c;
}
""", "upstream"),
    case("upstream-mid", """int f(int a) {
    int b = a + 1;
    int c = |b * 2;
    return c;
}
""", "upstream"),
    case("two-functions", """int g(int k) {
    int m = k + 1;
    return m;
}
int h(int j) {
    int n = |j * 3;
    return n;
}
"""),
    case("compound", """int f(int a) {
    int b = a + 1;
    b += 2;
    int c = |b * 3;
    return c;
}
"""),
    case("compound-up", """int f(int a) {
    int b = a + 1;
    b *= 2;
    int c = b + 1;
    return |c;
}
""", "upstream"),
    case("modulo", """int f(int a) {
    int b = a % 3;
    int c = |b + 1;
    return c;
}
"""),
    case("sel-def-site", """int f(int a) {
    int b = |a + 1;
    int c = b * 2;
    return c;
}
"""),
]

# ---------------------------------------------------------------------------
# Held-out suite (written after the weights were frozen).
# ---------------------------------------------------------------------------
HOLD += [
    case("h-long-chain", """int process(int seed) {
    int alpha = |seed + 5;
    int beta = alpha * 2;
    int gamma = beta + alpha;
    int delta = gamma - 1;
    return delta;
}
"""),
    case("h-rename", """int calc(int q, int r) {
    int tmp0 = q + 1;
    int tmp1 = |tmp0;
    int tmp2 = tmp1 * 4;
    return tmp2;
}
"""),
    case("h-irrelevant-insert", """int f(int a) {
    int b = |a + 1;
    int junk1 = 12345;
    int junk2 = junk1 + 1;
    int c = b * 2;
    return c;
}
"""),
    case("h-other-var-noise", """int f(int a, int other) {
    int b = |a * 6;
    int o1 = other + 1;
    int o2 = o1 * 3;
    int c = b + o2;
    return c;
}
"""),
    case("h-many-reads", """int f(int a) {
    int v = |a + 1;
    int p = v;
    int q = v;
    int r = p + q + v;
    return r;
}
"""),
    case("h-upstream-deep", """int f(int a) {
    int b = a + 1;
    int c = b * 2;
    int d = c + 3;
    return |d;
}
""", "upstream"),
    case("h-comment-between", """int f(int a) {
    int b = |a
            + 1;   /* folded */
    int c = b * 2;
    return c;
}
"""),
    case("h-params-only", """int f(int first, int second) {
    int out = |first + second;
    return out;
}
"""),
]


def score(src, pred, exp, spans):
    n = len(src)
    fp = fn = 0
    tp = 0
    for i in range(n):
        p, e = pred[i], exp[i]
        if p and not e:
            fp += 1
        elif e and not p:
            fn += 1
        elif p and e:
            tp += 1
    slices = ok_slices = 0
    for (s, e) in spans:
        slices += 1
        if all(pred[i] == exp[i] for i in range(s, e)):
            ok_slices += 1
    return dict(fp=fp, fn=fn, tp=tp, slices=slices, ok=ok_slices)


def run(cases, fl, verbose=True):
    tot = dict(fp=0, fn=0, tp=0, slices=0, ok=0)
    bad = []
    for c in cases:
        try:
            r = fl.analyze(c["src"], c["cursor"], c["mode"])
        except Unsupported as e:
            bad.append((c["name"], f"unsupported: {e}"))
            continue
        exp = ref.analyze(c["src"], c["cursor"], c["mode"])
        s = score(c["src"], r["labels"], exp["labels"], exp["spans"])
        for k in tot:
            tot[k] += s[k]
        if s["ok"] != s["slices"] or s["fp"] or s["fn"]:
            bad.append((c["name"], s))
        if verbose:
            flag = "ok " if (s["ok"] == s["slices"] and not s["fp"] and
                             not s["fn"]) else "FAIL"
            print(f"  {flag} {c['name']:20s} slices {s['ok']}/{s['slices']} "
                  f"fp={s['fp']} fn={s['fn']}")
    return tot, bad


MULTI = """int demo(int input, int ignored) {
    int x = input + 1;
    int saved = x;
    x = 0;
    int unrelated = ignored * 2;
    int result = saved * 3;
    return result;
}
"""


def every_cursor(fl, src):
    """Every identifier occurrence in one program, both modes."""
    import ref as _ref
    toks, _ = _ref.tokenize(src)
    occ = [t["start"] for t in toks
           if _ref.is_ident(t) and t["text"] not in _ref.KW]
    req = ok = 0
    for cur in occ:
        for mode in ("downstream", "upstream"):
            req += 1
            e = _ref.analyze(src, cur, mode)
            r = fl.analyze(src, cur, mode)
            if r["labels"] != e["labels"]:
                print("   FAIL cursor", cur, mode, repr(src[cur:cur + 9]))
            else:
                ok += 1
    return req, ok


def main():
    fl = FlowLens()
    print("== development ==")
    dt, dbad = run(DEV, fl)
    print("   totals:", dt)
    req, ok = every_cursor(fl, MULTI)
    print(f"  same-program every-cursor sweep: {ok}/{req} exact")
    print("== held-out ==")
    ht, hbad = run(HOLD, fl)
    print("   totals:", ht)
    with open(os.path.join(os.path.dirname(__file__), "last_eval.json"), "w") as f:
        json.dump(dict(dev=dt, hold=ht), f, indent=2)
    return 0 if not dbad and not hbad else 1


if __name__ == "__main__":
    sys.exit(main())
