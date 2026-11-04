import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.model import FlowLens

SRC = """int demo(int input, int ignored) {
    int x = input + 1;
    int saved = x;
    x = 0;
    int unrelated = ignored * 2;
    int result = saved * 3;
    return result;
}
"""

fl = FlowLens()
# select the read of x on line 3 ("int saved = x;")
cur = SRC.index("saved = x") + len("saved = ")
print("cursor at", cur, repr(SRC[cur:cur + 6]))
r = fl.analyze(SRC, cur, "downstream")
print("tokens", r["tokens"], "defs", r["n_def"], "rets", r["n_ret"], "anom", r["anomalies"])
print("value", r["selected_value"], "relevant tokens", r["relevant_tokens"])
for sp in r["spans"]:
    print(f"  tok{sp['tok']:3d} [{sp['start']:3d},{sp['end']:3d}) role={sp['role']} slot={sp['slot']:2d} lab={sp['label']} {SRC[sp['start']:sp['end']]!r}")

# render
out = []
for i, ch in enumerate(SRC):
    l = r["labels"][i]
    out.append("[" + ch + "]" if l == 2 else ("{" + ch + "}" if l == 1 else ch))
print("".join(out))
