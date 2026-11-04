#!/usr/bin/env python3
"""FlowLens command line: analyse one file at one position.

    python3 -m engine.cli FILE [-l LINE] [-c COL] [-m downstream|upstream]
                               [--json] [--inspect] [--all]

Positions are 1-based and COL counts bytes, exactly like Vim's cursor().
With no -l/-c the first identifier under or after the cursor is used at
line 1, column 1.

The output is the same data the Vim plugin renders: per-byte labels,
coalesced into ranges, plus the network's own trace.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.model import FlowLens, Unsupported  # noqa: E402


def byte_offset(text, line, col):
    lines = text.split("\n")
    if line < 1 or line > len(lines):
        raise Unsupported("line %d outside the file" % line)
    # byte offsets, like Vim's cursor() columns
    off = sum(len(l.encode("utf-8")) + 1 for l in lines[: line - 1])
    return off + max(0, col - 1)


def render(text, labels):
    out = []
    for i, ch in enumerate(text):
        lab = labels[i]
        if lab == 2:
            out.append("[" + ch + "]")
        elif lab == 1:
            out.append("{" + ch + "}")
        else:
            out.append(ch)
    return "".join(out)


def main():
    ap = argparse.ArgumentParser(prog="flowlens")
    ap.add_argument("file", nargs="?", help="C file ('-' for stdin)")
    ap.add_argument("-l", "--line", type=int, default=1)
    ap.add_argument("-c", "--col", type=int, default=1)
    ap.add_argument("-m", "--mode", default="downstream",
                    choices=["downstream", "upstream"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--all", action="store_true",
                    help="analyse every identifier occurrence, both modes")
    a = ap.parse_args()

    if not a.file or a.file == "-":
        text = sys.stdin.read()
    else:
        with open(a.file, "rb") as f:
            text = f.read().decode("utf-8", "replace")

    fl = FlowLens()
    if a.all:
        rows = []
        for i, ch in enumerate(text):
            if not (ch.isalpha() or ch == "_"):
                continue
            if i and (text[i - 1].isalnum() or text[i - 1] == "_"):
                continue
            for mode in ("downstream", "upstream"):
                try:
                    r = fl.analyze(text, i, mode)
                except Unsupported:
                    continue
                if r["selected_value"] == 0:
                    continue
                rows.append("%4d %-11s %-32s value=%2d rel=%2d anom=%d"
                            % (i, mode, repr(text[i:i + 12].split("\n")[0]),
                               r["selected_value"], r["relevant_tokens"],
                               r["anomalies"]))
        print("\n".join(rows) if rows else "(no value-carrying occurrences)")
        return 0

    cur = byte_offset(text, a.line, a.col)
    try:
        r = fl.analyze(text, cur, a.mode)
    except Unsupported as e:
        print("unsupported: %s" % e, file=sys.stderr)
        return 2

    if a.json:
        print(json.dumps({k: v for k, v in r.items() if k != "labels"},
                         indent=2))
        return 0

    print("file %s  cursor %d (%r)  mode %s" %
          (a.file or "<stdin>", cur, text[cur:cur + 12].split("\n")[0], a.mode))
    print("tokens %d  definitions %d  return sinks %d  anomalies %d"
          % (r["tokens"], r["n_def"], r["n_ret"], r["anomalies"]))
    print("selected value node %d   relevant identifier tokens %d"
          % (r["selected_value"], r["relevant_tokens"]))
    print("encode %.2f ms  infer %.2f ms  MACs %d  tensor ops %d"
          % (r["encode_ms"], r["infer_ms"], r["macs"], r["op_count"]))
    if r["anomalies"]:
        print("WARNING: %d token(s) outside the supported subset - labels may "
              "be incomplete (see docs/SEMANTICS.md)" % r["anomalies"])
    print("\n{} = relevant   [] = selected\n")
    print(render(text, r["labels"]))
    if a.inspect:
        print("\ntoken  span         role  slot  text")
        for sp in r["spans"]:
            txt = text[sp["start"]:sp["end"]]
            print("%5d  [%4d,%4d)  %s   %3d   %s"
                  % (sp["tok"], sp["start"], sp["end"],
                     "read" if sp["role"] == 1 else
                     "def " if sp["role"] == 2 else "    ",
                     sp["slot"], txt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
