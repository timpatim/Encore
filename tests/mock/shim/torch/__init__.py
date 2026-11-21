"""Tiny numpy-backed stand-in for the few torch calls used by H3 Clip Plan (tests only)."""
import pickle
import numpy as np
float32 = np.float32

class Tensor(np.ndarray):
    def unsqueeze(self, d): return np.expand_dims(self, d).view(Tensor)
    def repeat(self, *r): return _t(np.tile(np.asarray(self), r))
    def to(self, *a, **k): return self
    def detach(self): return self
    def contiguous(self): return self
    def clone(self): return self.copy()
    def movedim(self, a, b): return np.moveaxis(self, a, b).view(Tensor)
    def unbind(self): return list(self)
    def numpy(self): return np.asarray(self)

def _t(a): return np.asarray(a, dtype=np.float32).view(Tensor)
def _shape(args): return tuple(args[0]) if len(args) == 1 and isinstance(args[0], (tuple, list)) else tuple(args)
def zeros(*s, **k): return _t(np.zeros(_shape(s)))
def ones(*s, **k): return _t(np.ones(_shape(s)))
def randn(*s, **k): return _t(np.random.randn(*_shape(s)))
def full(s, v, **k): return _t(np.full(tuple(s), v))
def full_like(x, v): return _t(np.full(x.shape, v))
def from_numpy(a): return _t(a)
def std(x, dim, keepdim=False): return _t(np.std(np.asarray(x), axis=tuple(dim), keepdims=keepdim, ddof=1))
def save(obj, path):
    with open(path, "wb") as f: pickle.dump(obj, f)
def load(path, **k):
    with open(path, "rb") as f: return pickle.load(f)
from . import nn
