"""Unsupported-construct detection test.

The network must not silently pretend to analyse what it does not model.
Two-token-lookahead weight rules flag constructs outside the documented
subset; this test asserts they fire, and that supported programs stay clean.

This checks *detection*, not analysis: flagged programs still produce
labels, and the plugin warns that they may be incomplete.

Run:  python3 tests/anomaly.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.model import FlowLens

UNSUPPORTED = {
    "nested-unbraced": "int f(int a){\n int b = 1;\n if (a) if (b) b = 2; else b = 3;\n return b;\n}\n",
    "shadowing": "int f(int a){\n int b = 1;\n { int b = 2; int c = b; }\n return b;\n}\n",
    "nested-paren-cond": "int f(int a, int b){\n int c = a + 1;\n if ((a + b) > 1) { c = 2; }\n return c;\n}\n",
    "pointer-param": "int f(int * p){\n int b = 2;\n return b;\n}\n",
    "pointer-decl": "int f(int a){\n int * p = 0;\n int b = a + 1;\n return b;\n}\n",
    "function-call": "int f(int a){\n int b = g(a);\n return b;\n}\n",
    "struct": "int f(int a){\n struct s x;\n int b = a + 1;\n return b;\n}\n",
    "cast": "int f(int a){\n int b = (int) a;\n return b;\n}\n",
    "array": "int f(int a){\n int v[4];\n int b = a + 1;\n return b;\n}\n",
    "ternary": "int f(int a){\n int b = a ? 1 : 2;\n return b;\n}\n",
    "else-clause": "int f(int a){\n int b = 1;\n else { b = 2; }\n return b;\n}\n",
}

SUPPORTED = {
    "basic": "int demo(int input, int ignored) {\n int x = input + 1;\n int saved = x;\n x = 0;\n int unrelated = ignored * 2;\n int result = saved * 3;\n return result;\n}\n",
    "if-unbraced": "int f(int a){\n int b = a + 1;\n if (b) b = 2;\n return b;\n}\n",
    "else-if-chain": "int f(int a){\n int b = 1;\n if (a) b = 2;\n else if (a > 1) b = 3;\n else b = 4;\n return b;\n}\n",
    "while-unbraced": "int f(int a){\n int b = a + 1;\n while (b) b = b - 1;\n return b;\n}\n",
    "do-while": "int f(int a){\n int b = a + 1;\n do { b = b - 1; } while (b);\n return b;\n}\n",
    "for-loop": "int f(int a){\n int s = 0;\n for (int i = 0; i < 3; i = i + 1) { s = s + i; }\n return s;\n}\n",
    "for-postfix": "int f(int n){\n int s = 0;\n for (int i = 0; i < n; i++) { s = s + i; }\n return s;\n}\n",
    "for-unbraced": "int f(int n){\n int s = 0;\n for (int i = 0; i < n; i++) s = s + i;\n return s;\n}\n",
    "bare-block": "int f(int a){\n int s = 0;\n { s = a + 1; }\n return s;\n}\n",
    "two-functions-same-local": "int f(int a){\n int t = a + 1;\n return t;\n}\nint g(int b){\n int t = b * 2;\n return t;\n}\n",
    "nested-braced": "int f(int a){\n int s = 0;\n while (a) { if (s) { s = 1; } else { s = 2; } }\n return s;\n}\n",
    "compound": "int f(int a){\n int b = a + 1;\n b += 2;\n b *= 3;\n return b;\n}\n",
    "modulo": "int f(int a){\n int b = a % 3;\n return b;\n}\n",
    "parens": "int f(int a, int b){\n int c = (a + b) * 2;\n return c;\n}\n",
    "comments": "/* int z = 1; */ int f(int a){\n // z = 2;\n int b = a + 1;\n return b;  // trailling\n}\n",
}


def main():
    fl = FlowLens()
    bad = []
    for name, src in UNSUPPORTED.items():
        r = fl.analyze(src, src.index("return") + 7, "downstream")
        flag = "detected" if r["anomalies"] > 0 else "MISSED"
        print(f"  {flag:9s} {name:16s} anomalies={r['anomalies']}")
        if r["anomalies"] == 0:
            bad.append(name)
    print()
    for name, src in SUPPORTED.items():
        r = fl.analyze(src, src.index("return") + 7, "downstream")
        flag = "clean" if r["anomalies"] == 0 else "FALSE-ALARM"
        print(f"  {flag:11s} {name:12s} anomalies={r['anomalies']}")
        if r["anomalies"]:
            bad.append(name)
    print("\nfailures:", bad if bad else "none")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
