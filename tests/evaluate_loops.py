"""Development suite for loops and single-statement bodies (v3 constructs).

Every identifier occurrence is selected in turn, in both modes, and the
network's labels are compared token-for-token with tests/ref.py.  The
reference is test-only; it never feeds inference.

Run:  python3 tests/evaluate_loops.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.model import FlowLens
import tests.ref as ref

PROGRAMS = {
"for-accum": """\
int f(int n) {
    int s = 0;
    for (int i = 0; i < n; i++) {
        s = s + i;
    }
    return s;
}
""",
"for-copy-chain": """\
int g(int limit) {
    int acc = 0;
    for (int k = 0; k < limit; k++) {
        int step = k + 1;
        int scaled = step * 2;
        acc = acc + scaled;
    }
    return acc;
}
""",
"for-self-assign-step": """\
int h(int n) {
    int total = 1;
    for (int i = apo; i < n; i = i + 1) {
        total = total * 2;
    }
    return total;
}
""",
"for-compound-step": """\
int h2(int n) {
    int total = 1;
    for (int i = 0; i < n; i += 2) {
        total = total + i;
    }
    return total;
}
""",
"for-empty-init": """\
int h3(int start, int n) {
    int r = start;
    for (; r < n; r++) {
        r = r + 1;
    }
    return r;
}
""",
"for-in-if": """\
int h4(int n, int flag) {
    int out = 0;
    if (flag) {
        for (int i = 0; i < n; i++) {
            out = out + i;
        }
    }
    int last = out;
    return last;
}
""",
"for-two-loops": """\
int h5(int n) {
    int a = 0;
    for (int i = 0; i < n; i++) {
        a = a + i;
    }
    int b = a;
    for (int j = 0; j < n; j++) {
        b = b - j;
    }
    return b;
}
""",
"for-unbraced": """\
int h6(int n) {
    int s = 0;
    for (int i = 0; i < n; i++) s = s + i;
    return s;
}
""",
"unbraced-if": """\
int u1(int a, int b) {
    int r = 0;
    if (a > b) r = a;
    int q = r + 1;
    return q;
}
""",
"unbraced-if-else": """\
int u2(int a) {
    int r = 1;
    if (a) r = a * 2;
    else r = a + 3;
    int q = r;
    return q;
}
""",
"else-if-chain": """\
int u3(int a) {
    int r = 1;
    if (a) r = 2;
    else if (a > 1) r = 3;
    else r = 4;
    int q = r;
    return q;
}
""",
"unbraced-while": """\
int u4(int n) {
    int v = n;
    while (v) v = v - 1;
    int w = v;
    return w;
}
""",
"do-while-braced": """\
int d1(int n) {
    int v = n;
    do {
        v = v - 1;
    } while (v);
    int w = v;
    return w;
}
""",
"do-while-unbraced": """\
int d2(int n) {
    int v = n;
    do v = v - 1; while (v);
    int w = v;
    return w;
}
""",
"unbraced-in-braced": """\
int u5(int a, int b) {
    int t = 0;
    while (a) {
        if (b) t = a + b;
        else t = a - b;
        a = a - 1;
    }
    return t;
}
""",
"two-functions": """\
int alpha(int a) {
    int t = a + 2;
    return t;
}
int omega(int b) {
    int u = b * 3;
    return u;
}
""",
"bare-block": """\
int u6(int a) {
    int s = 0;
    {
        s = a + 1;
    }
    int r = s;
    return r;
}
""",
}

MODES = ("downstream", "upstream")


def score(src, pred, exp, spans):
    fp = fn = tp = 0
    for (s0, e0) in spans:
        p = 1 if pred[s0] else 0
        q = 2 if exp[s0] == 2 else (1 if exp[s0] else 0)
        if p and not q:
            fp += 1
        elif q and not p:
            fn += 1
        elif p and q == 1:
            tp += 1
    return fp, fn, tp


def main():
    fl = FlowLens()
    tot = dict(fp=0, fn=0, tp=0, slices=0, ok=0)
    fails = []
    for name, src in PROGRAMS.items():
        srcb = src.encode()
        exp0 = ref.analyze(src, 0, "downstream")
        spans = [(a, b) for (a, b) in exp0["spans"]
                 if src[a:b] not in ref.KW]
        s_fp = s_fn = s_tp = s_slices = s_ok = 0
        anomalies = 0
        for t, (s0, _) in enumerate(spans):
            for mode in MODES:
                exp = ref.analyze(src, s0, mode)
                got = fl.analyze(srcb, s0, mode)
                anomalies = max(anomalies, got["anomalies"])
                fp, fn, tp = score(src, got["labels"], exp["labels"], spans)
                s_fp += fp
                s_fn += fn
                s_tp += tp
                for (a, _b) in spans:
                    want = exp["labels"][a] > 0
                    have = got["labels"][a] > 0
                    s_slices += 1
                    if want == have:
                        s_ok += 1
                if fp or fn:
                    fails.append((name, s0, mode, src[0:0]))
        for k, v in (("fp", s_fp), ("fn", s_fn), ("tp", s_tp),
                     ("slices", s_slices), ("ok", s_ok)):
            tot[k] += v
        flag = "ok " if (s_ok == s_slices and not s_fp and not s_fn) else "FAIL"
        print(f"  {flag} {name:22s} slices {s_ok}/{s_slices} "
              f"fp={s_fp} fn={s_fn} anomalies={anomalies}")
    print(f"\n  totals: {tot}")
    if fails:
        print(f"  first failing selections: {fails[:5]}")
    return 0 if (tot["ok"] == tot["slices"] and not tot["fp"] and
                 not tot["fn"]) else 1


if __name__ == "__main__":
    sys.exit(main())
