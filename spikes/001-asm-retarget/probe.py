"""Measure what a retarget to assembly would buy and cost.

Compiles the demo at -O0 and -O2, then reports the shape of the input the
network would see: instruction count, vocabulary size, register file, label
count, and how well instructions map back to source lines and columns.

Run:  python3 spikes/001-asm-retarget/probe.py
"""

import collections
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "demo.c")

REG = re.compile(r"^%?([xw]\d+|sp|lr|fp|x29|x30|wsp|wzr|xzr)$")


def compile_to(asm, opt):
    subprocess.run(["clang", "-S", "-g", opt, "-o", asm, SRC], check=True)


def parse(asm_path, src_path):
    src = open(src_path).read()
    lines = open(asm_path).read().split("\n")
    instrs, mnemonics, regs, labels = [], collections.Counter(), set(), set()
    locs, func = [], None
    funcs = set()
    globls = set()
    targets = collections.Counter()
    cur_line = None
    per_line = collections.Counter()
    for ln in lines:
        t = ln.strip()
        if t.startswith(".loc"):
            parts = t.split()
            if len(parts) >= 3:
                cur_line = int(parts[2])
                locs.append((parts[1], cur_line,
                             int(parts[3]) if len(parts) > 3 else 0))
        elif t.startswith(".globl"):
            func = t.split()[1]
            globls.add(func)
        elif re.match(r"^[A-Za-z_]\w*:$", t):
            labels.add(t[:-1])
            if func and not t.startswith(".L"):
                funcs.add(t[:-1])
        elif t and not t.startswith(".") and not t.startswith("//"):
            m = re.match(r"^([a-z][\w.]*)\s*(.*)$", t)
            if not m:
                continue
            mn = m.group(1)
            mnemonics[mn] += 1
            instrs.append(t)
            for tok in re.split(r"[,\s\[\]{}!]+", m.group(2)):
                mm = REG.match(tok)
                if mm:
                    regs.add(mm.group(1))
            if cur_line:
                per_line[cur_line] += 1
            if mn.startswith(("b", "cb", "tb")):
                targets[m.group(2).strip()] += 1
    return dict(src_bytes=len(src), src_lines=src.count("\n"),
                asm_lines=len(lines), instrs=len(instrs),
                mnemonics=len(mnemonics), top_mnemonics=mnemonics.most_common(8),
                regs=len(regs), reg_names=sorted(regs), labels=len(labels),
                funcs=sorted(globls), locs=len(locs),
                blocks=len([t for t in targets if t in labels]),
                src_lines_mapped=len(per_line),
                per_line=per_line, loc_sample=locs[:4])


def main():
    out = {}
    for opt in ("-O0", "-O2"):
        asm = os.path.join(HERE, "demo%s.s" % opt)
        compile_to(asm, opt)
        d = parse(asm, SRC)
        out[opt] = d
        print("== %s" % opt)
        print("  source: %d bytes, %d lines" % (d["src_bytes"], d["src_lines"]))
        print("  asm:    %d lines, %d instructions, %d distinct mnemonics"
              % (d["asm_lines"], d["instrs"], d["mnemonics"]))
        print("  vocabulary top: %s" % (d["top_mnemonics"],))
        print("  registers used: %d %s" % (d["regs"], d["reg_names"]))
        print("  functions defined: %s" % (d["funcs"],))
        print("  basic blocks (branch targets that are labels): %d"
              % d["blocks"])
        print("  .loc directives: %d covering %d source lines"
              % (d["locs"], d["src_lines_mapped"]))
        if d["per_line"]:
            counts = sorted(d["per_line"].values())
            med = counts[len(counts) // 2]
            print("  instructions per source line: median %d, max %d"
                  % (med, counts[-1]))
        print("  first .loc entries: %s" % (d["loc_sample"],))
        print()

    o0, o2 = out["-O0"], out["-O2"]
    print("== what changed at -O2")
    print("  instructions: %d -> %d (%.2fx)"
          % (o0["instrs"], o2["instrs"], o2["instrs"] / max(1, o0["instrs"])))
    print("  source lines still mapped: %d -> %d"
          % (o0["src_lines_mapped"], o2["src_lines_mapped"]))
    print("  functions present: %d -> %d  (%s)"
          % (len(o0["funcs"]), len(o2["funcs"]), o2["funcs"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
