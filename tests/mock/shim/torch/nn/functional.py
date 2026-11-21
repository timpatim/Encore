import numpy as np
from .. import _t
def interpolate(x, size, mode="linear", align_corners=False):
    x = np.asarray(x); n = x.shape[-1]
    src = (np.arange(size) + 0.5) * n / size - 0.5
    src = np.clip(src, 0, n - 1)
    lo = np.floor(src).astype(int); hi = np.minimum(lo + 1, n - 1); f = src - lo
    return _t(x[..., lo] * (1 - f) + x[..., hi] * f)
def pad(x, p):
    return _t(np.pad(np.asarray(x), [(0, 0)] * (x.ndim - 1) + [(p[0], p[1])]))
