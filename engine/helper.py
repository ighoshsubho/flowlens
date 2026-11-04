#!/usr/bin/env python3
"""FlowLens persistent helper for Vim.

Speaks newline-delimited JSON on stdin/stdout.  Holds the frozen weights and
the generic inference runtime only: it contains no C analysis of its own.

Request:
  {"id": 3, "tick": 12, "text": "...", "cursor": 74, "mode": "downstream",
   "inspect": false}

Response:
  {"id": 3, "tick": 12, "ok": true,
   "ranges": [[start_byte, end_byte, label], ...],
   "stats": {...}, "timings": {...}}
  label 1 = relevant, 2 = selected.

All ranges are byte offsets into the exact text that was sent, so a Vim
buffer with unsaved edits is analysed as it stands.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.model import FlowLens, Unsupported  # noqa: E402


def ranges_from_labels(labels):
    """Coalesce adjacent equal labels; this never adds or moves relevance."""
    out = []
    n = len(labels)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and labels[j + 1] == labels[i]:
            j += 1
        if labels[i]:
            out.append([i, j + 1, int(labels[i])])
        i = j + 1
    return out


def main():
    t_cold = time.perf_counter()
    fl = FlowLens()
    cold_ms = (time.perf_counter() - t_cold) * 1000.0
    out = sys.stdout
    out.write(json.dumps({"hello": True, "cold_ms": cold_ms,
                          "stats": fl.stats()}) + "\n")
    out.flush()
    cache = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as e:                        # noqa: BLE001
            out.write(json.dumps({"ok": False, "error": "bad json: %s" % e})
                      + "\n")
            out.flush()
            continue
        rid = req.get("id")
        tick = req.get("tick")
        if req.get("op") == "quit":
            break
        text = req.get("text", "")
        cursor = int(req.get("cursor", 0))
        mode = req.get("mode", "downstream")
        key = (hash(text), len(text), cursor, mode)
        t0 = time.perf_counter()
        try:
            if key in cache:
                r = cache[key]
            else:
                r = fl.analyze(text, cursor, mode)
                if len(cache) > 64:
                    cache.clear()
                cache[key] = r
            reply = {
                "id": rid, "tick": tick, "ok": True,
                "ranges": ranges_from_labels(r["labels"]),
                "stats": {
                    "tokens": r["tokens"], "anomalies": r["anomalies"],
                    "n_def": r["n_def"], "n_ret": r["n_ret"],
                    "relevant_tokens": r["relevant_tokens"],
                    "selected_value": r["selected_value"],
                    "macs": r["macs"], "op_count": r["op_count"],
                },
                "timings": {
                    "encode_ms": r["encode_ms"],
                    "infer_ms": r["infer_ms"],
                    "total_ms": (time.perf_counter() - t0) * 1000.0,
                },
            }
            if req.get("inspect"):
                reply["inspect"] = {
                    "tokens": r["tokens"], "anomalies": r["anomalies"],
                    "selected_token": r["selected_token"],
                    "selected_value": r["selected_value"],
                    "n_def": r["n_def"], "n_ret": r["n_ret"],
                    "macs": r["macs"], "elem_ops": r["elem_ops"],
                    "op_count": r["op_count"],
                    "spans": r["spans"],
                    "limits": fl.L,
                    "cold_ms": cold_ms,
                }
        except Unsupported as e:
            reply = {"id": rid, "tick": tick, "ok": False,
                     "error": "unsupported: %s" % e}
        except Exception as e:                        # noqa: BLE001
            reply = {"id": rid, "tick": tick, "ok": False,
                     "error": "%s: %s" % (type(e).__name__, e)}
        out.write(json.dumps(reply) + "\n")
        out.flush()


if __name__ == "__main__":
    main()
