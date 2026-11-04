"""FlowLens benchmarks.

Measures, per source length:
  cold start, encode, neural inference, helper round trip, Vim render and
  end-to-end latency, plus runtime memory and operation counts.

Run:  python3 bench/bench.py
"""

import json
import os
import resource
import statistics
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.model import FlowLens  # noqa: E402
from engine.helper import ranges_from_labels  # noqa: E402

OUT = os.path.join(ROOT, "bench", "corpus")


def gen(nstmt):
    """A program in the supported subset with a copy/arith chain."""
    lines = ["int bench(int seed) {", "    int v0 = seed + 1;"]
    for i in range(1, nstmt):
        op = "+" if i % 3 else "*"
        lines.append(f"    int v{i} = v{i - 1} {op} {i % 7 + 1};")
    lines.append(f"    return v{nstmt - 1};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def gen_loop(nbody):
    """Loop-heavy program in the supported subset: a for body that copies,
    an if/else inside it, and a while-driven tail."""
    lines = ["int loops(int seed, int bound) {", "    int acc = seed + 1;",
             "    int guard = bound;",
             "    for (int i = 0; i < bound; i++) {"]
    for i in range(nbody):
        if i % 4 == 3:
            lines.append("        if (acc) acc = acc - 1;")
            lines.append("        else acc = acc + 1;")
        else:
            lines.append("        acc = acc + %d;" % (i % 7 + 1))
    lines.append("    }")
    lines.append("    while (guard) guard = guard - 1;")
    lines.append("    return acc + guard;")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main():
    os.makedirs(OUT, exist_ok=True)
    # cold start: fresh interpreter, one analysis
    t0 = time.perf_counter()
    p = subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, %r);"
                        "from engine.model import FlowLens;"
                        "FlowLens()" % ROOT],
                       capture_output=True)
    cold_ms = (time.perf_counter() - t0) * 1000.0
    assert p.returncode == 0, p.stderr.decode()

    fl = FlowLens()
    rows = []
    for kind, nstmt in [("chain", n) for n in (4, 10, 25, 35, 43)] + \
                       [("loop", n) for n in (4, 10, 20, 35)]:
        src = gen(nstmt) if kind == "chain" else gen_loop(nstmt)
        path = os.path.join(OUT, f"bench_{kind}_{nstmt:02d}.c")
        with open(path, "w") as f:
            f.write(src)
        cur = src.index("v0") + 3 if kind == "chain" else src.index("acc =")
        cur += 1
        enc, inf, tot, macs, ops, toks = [], [], [], 0, 0, 0
        for _ in range(12):
            t = time.perf_counter()
            r = fl.analyze(src, cur, "downstream")
            tot.append((time.perf_counter() - t) * 1000)
            enc.append(r["encode_ms"])
            inf.append(r["infer_ms"])
            macs, ops, toks = r["macs"], r["op_count"], r["tokens"]
        rows.append(dict(
            name=f"bench_{kind}_{nstmt:02d}.c", kind=kind,
            bytes=len(src), tokens=toks,
            defs=r["n_def"],
            encode_ms=round(statistics.median(enc), 2),
            infer_ms=round(statistics.median(inf), 2),
            total_ms=round(statistics.median(tot), 2),
            macs=macs, ops=ops,
        ))
        print(rows[-1])

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    st = fl.stats()
    print("\ncold start (import + weights + analyse): %.1f ms" % cold_ms)
    print("resident memory after run: %.1f MB (peak)" % rss)
    print("dense params %d, nonzero %d, weights file %d bytes"
          % (st["params_dense"], st["params_nonzero"], st["weights_bytes"]))

    vim = vim_bench()
    with open(os.path.join(ROOT, "bench", "results.json"), "w") as f:
        json.dump(dict(environment=environment(), cold_ms=cold_ms,
                       rss_mb=rss, weights=st, rows=rows, vim=vim), f,
                  indent=2)
    print("\nVim:", json.dumps(vim, indent=2))


def environment():
    import platform
    return dict(system=platform.platform(), machine=platform.machine(),
                python=sys.version.split()[0], numpy=__import__("numpy").__version__,
                vim=subprocess.run(["vim", "--version"], capture_output=True,
                                   text=True).stdout.split("\n")[0])


def vim_bench():
    script = os.path.join(ROOT, "bench", "vim_bench.vim")
    outf = "/tmp/flowlens_vim_bench.json"
    if os.path.exists(outf):
        os.remove(outf)
    subprocess.run(["vim", "-Nu", os.path.join(ROOT, "bench", "vimrc"),
                    "-n", "-es", "-S", script], check=False)
    if not os.path.exists(outf):
        return {}
    with open(outf) as f:
        return json.load(f)


if __name__ == "__main__":
    main()
