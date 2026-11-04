import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ref
from engine.model import FlowLens

fl = FlowLens()
SRC = open(sys.argv[1]).read()
CUR = int(sys.argv[2])
MODE = sys.argv[3] if len(sys.argv) > 3 else "downstream"

r = fl.analyze(SRC, CUR, MODE)
e = ref.analyze(SRC, CUR, MODE)
print("cursor", CUR, repr(SRC[CUR:CUR + 6]), "mode", MODE)
print("model value", r["selected_value"], "ref value", e["value"],
      "anom", r["anomalies"])
toks, _ = ref.tokenize(SRC)
for t in toks:
    if not ref.is_ident(t) or t["text"] in ref.KW:
        continue
    s, en = t["start"], t["end"]
    m = r["labels"][s]
    x = e["labels"][s]
    flag = "  " if m == x else "!!"
    print(f"{flag} {t['text']:9s} [{s:4d},{en:4d}) pred={m} exp={x}")
print("".join(("[%s]" % c) if r["labels"][i] == 2 else
              ("{%s}" % c) if r["labels"][i] == 1 else c
              for i, c in enumerate(SRC)))
