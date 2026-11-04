"""Reproducible demo: labels straight from the neural engine.

Run:  python3 scripts/demo.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.model import FlowLens

DEMO = """int demo(int input, int ignored) {
    int x = input + 1;
    int saved = x;
    x = 0;
    int unrelated = ignored * 2;
    int result = saved * 3;
    return result;
}
"""

UP = """int proc(int seed) {
    int a = seed + 1;
    int b = a * 2;
    int c = b + a;
    return c;
}
"""

KILL = """int f(int a) {
    int y = a + 1;
    int keep = y;
    y = 9;
    y = y + 1;
    return keep;
}
"""


def show(fl, src, cursor, mode, title):
    r = fl.analyze(src, cursor, mode)
    line = []
    for i, ch in enumerate(src):
        lab = r["labels"][i]
        if lab == 2:
            line.append("[" + ch + "]")
        elif lab == 1:
            line.append("{" + ch + "}")
        else:
            line.append(ch)
    print("=" * 72)
    print(title)
    print("  cursor byte %d (%r)  mode=%s  tokens=%d  value-node=%d"
          % (cursor, src[cursor:cursor + 8], mode, r["tokens"],
             r["selected_value"]))
    print("  encode %.2f ms  infer %.2f ms  anomalies %d  macs %d"
          % (r["encode_ms"], r["infer_ms"], r["anomalies"], r["macs"]))
    print("  {} = relevant   [] = selected")
    for ln in "".join(line).split("\n"):
        print("   " + ln)
    print()


def main():
    fl = FlowLens()
    show(fl, DEMO, DEMO.index("saved = x") + 8, "downstream",
         "1. downstream from the ORIGINAL x: copies flow, the later x = 0 does not")
    show(fl, DEMO, DEMO.index("return result") + 7, "upstream",
         "2. upstream from the returned value")
    show(fl, KILL, KILL.index("keep = y") + 7, "downstream",
         "3. a definition that is later overwritten keeps its own flow")
    show(fl, UP, UP.index("c = b + a") + 4, "upstream",
         "4. upstream of c: both arithmetic inputs, transitively")
    st = fl.stats()
    print("weights: %d dense params, %d nonzero, %d bytes on disk"
          % (st["params_dense"], st["params_nonzero"], st["weights_bytes"]))


if __name__ == "__main__":
    main()
