"""Fresh held-out suite for loops and single-statement bodies.

Written after the v3 weights were frozen and disjoint from the development
programs in tests/evaluate_loops.py: different identifier names, different
formatting (tabs, all-on-one-line, comments between clauses), different loop
shapes.  The reference in tests/ref.py supplies expected labels; the network
never sees it.

Run:  python3 tests/holdout_loops.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.model import FlowLens
import tests.ref as ref

PROGRAMS = {
"reduce-scaled": """\
int reduce2(int count) {
    int acc = 0;
    for (int k = 0; k < count; k++) {
        acc = acc + k * 2;
    }
    return acc;
}
""",
"two-accums": """\
int split(int lim) {
    int upper = 0;
    int lower = lim;
    for (int step = 0; step < lim; step++) {
        if (step % 2) upper = upper + step;
        lower = lower - 1;
    }
    int out = upper + lower;
    return out;
}
""",
"do-accumulate": """\
int drain(int start, int whilee) {
    int left = start;
    do {
        left = left - whilee;
    } while (left);
    int rest = left;
    return rest;
}
""",
"for-in-while": """\
int nested(int bound, int rounds) {
    int total = 0;
    while (rounds) {
        for (int q = 0; q < bound; q++) {
            total = total + q;
        }
        rounds = rounds - 1;
    }
    return total;
}
""",
"bare-declare-then-set": """\
int staged(int src) {
	int first;
	first = src + 4;
	int second = first;
	for (int w = 0; w < src; w++) second = second + w;
	return second;
}
""",
"while-self-written": """\
int spin(int v) {
    int spins = 0;
    while (v)
        v = v - 1;
    spins = spins + 1;
    return spins;
}
""",
"chain-after-else": """\
int picker(int flag, int seed) {
    int slot = seed;
    if (flag) slot = seed + 1;
    else if (flag > 2) slot = seed * 2;
    else slot = 0;
    int carried = slot;
    return carried;
}
""",
"overwrite-induction": """\
int odd(int n) {
    int sum = 1;
    for (int c = 0; c < n; c++) {
        sum = sum * 3;
        c = c + 1;
    }
    return sum;
}
""",
"single-line-loop": """\
int one(int a) { int r = 0; for (int i = 0; i < a; i++) r = r + i; return r; }
""",
"comment-in-header": """\
int spaced(int limit) {
    int acc = 1;
    for (int i = 0; /* from zero */ i < limit; i += 1) {
        acc = acc * 2;   // double
    }
    return acc;
}
""",
}

MODES = ("downstream", "upstream")


def main():
    fl = FlowLens()
    tot = dict(fp=0, fn=0, tp=0, slices=0, ok=0, cases=0)
    fails = []
    anomalies = 0
    for name, src in PROGRAMS.items():
        sb = src.encode()
        spans = [(a, b) for (a, b) in ref.analyze(src, 0, "downstream")["spans"]
                 if src[a:b] not in ref.KW]
        s_ok = s_sl = s_fp = s_fn = 0
        for (s0, _) in spans:
            for mode in MODES:
                exp = ref.analyze(src, s0, mode)
                got = fl.analyze(sb, s0, mode)
                anomalies = max(anomalies, got["anomalies"])
                tot["cases"] += 1
                for (a, _b) in spans:
                    want = exp["labels"][a] > 0
                    have = got["labels"][a] > 0
                    s_sl += 1
                    tot["slices"] += 1
                    if want == have:
                        s_ok += 1
                        tot["ok"] += 1
                    elif have:
                        s_fp += 1
                        tot["fp"] += 1
                    else:
                        s_fn += 1
                        tot["fn"] += 1
                if s_fp or s_fn:
                    fails.append((name, s0, mode))
        flag = "ok " if (s_ok == s_sl) else "FAIL"
        print(f"  {flag} {name:22s} slices {s_ok}/{s_sl} fp={s_fp} fn={s_fn}")
    print(f"\n  cases {tot['cases']}  slices {tot['ok']}/{tot['slices']} exact "
          f"fp={tot['fp']} fn={tot['fn']} max_anomalies={anomalies}")
    if fails:
        print("  failing selections:", fails[:6])
    return 0 if (tot["ok"] == tot["slices"] and anomalies == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
