"""Generic tensor operations for FlowLens.

This module knows nothing about C.  It is a tiny tensor runtime: matmul,
outer products, elementwise products, winner-take-all, row gather/scatter,
and boolean reachability by repeated matmul.  Every architecture decision
lives in model.py (which composes these ops with tensors from the frozen
weight file), never here.
"""

import numpy as np

F = np.float32


class Ctx:
    """Counts work done by the runtime, for honest reporting."""

    __slots__ = ("macs", "elem", "ops")

    def __init__(self):
        self.macs = 0
        self.elem = 0
        self.ops = 0

    def reset(self):
        self.macs = 0
        self.elem = 0
        self.ops = 0


def mm(ctx, a, b):
    """Dense matmul.  Counts multiply-accumulates."""
    a = np.asarray(a, dtype=F)
    b = np.asarray(b, dtype=F)
    ctx.ops += 1
    # Accelerate (macOS system BLAS) raises spurious underflow/divide FP flags
    # for float32 sgemm; the returned values are exact. Silence the flag noise.
    with np.errstate(all="ignore"):
        out = a @ b
    ctx.macs += out.size * a.shape[-1]      # one multiply-add per output term
    return out


def outer(ctx, a, b):
    ctx.ops += 1
    ctx.elem += a.size * b.size
    return np.outer(a, b).astype(F)


def mul(ctx, a, b):
    ctx.ops += 1
    ctx.elem += a.size
    return (np.asarray(a, dtype=F) * np.asarray(b, dtype=F)).astype(F)


def add(ctx, a, b):
    ctx.ops += 1
    ctx.elem += max(a.size, b.size)
    return (np.asarray(a, dtype=F) + np.asarray(b, dtype=F)).astype(F)


def thresh(ctx, x, t=0.5):
    """Hard threshold: 1.0 where x > t."""
    ctx.ops += 1
    ctx.elem += x.size
    return (np.asarray(x, dtype=F) > t).astype(F)


def wta(ctx, logits):
    """Winner-take-all: one-hot of argmax.  Hard attention / discrete state."""
    ctx.ops += 1
    ctx.elem += logits.size
    out = np.zeros_like(logits, dtype=F)
    out[int(np.argmax(logits))] = 1.0
    return out


def row_gather(ctx, m, sel):
    """Content-addressed read: sel is a one-hot over rows of m."""
    ctx.ops += 1
    ctx.elem += m.size
    return (sel @ m).astype(F)


def row_scatter(ctx, m, sel, vec):
    """Content-addressed write: replace the selected row of m with vec."""
    ctx.ops += 1
    ctx.elem += m.size
    keep = (1.0 - sel)[:, None]
    return (keep * m + np.outer(sel, vec)).astype(F)


def reach(ctx, adj, steps):
    """Boolean transitive closure by repeated boolean matmul.

    adj[u, v] = 1 means "u depends on v".  Returns paths of length 1..steps.
    """
    r = (adj > 0.5).astype(F)
    power = r.copy()
    for _ in range(steps):
        power = (power @ r > 0).astype(F)
        ctx.ops += 1
        ctx.macs += r.shape[0] ** 3
        r = ((r + power) > 0).astype(F)
    return r


def onehot(i, n):
    v = np.zeros(n, dtype=F)
    if 0 <= i < n:
        v[i] = 1.0
    return v
