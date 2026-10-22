"""Many quads in one draw call: stars, meteor trails, aurora rays.

A ``QuadBatch`` owns preallocated vertex and index buffers, so a frame with
thousands of twinkling stars costs a few NumPy operations and a single
``SDL_RenderGeometry`` call, and allocates nothing.
"""

from __future__ import annotations

import numpy as np

from .canvas import BLEND, VERTEX, Canvas, Texture

_CORNER_U = np.array([0.0, 1.0, 1.0, 0.0], np.float32)
_CORNER_V = np.array([0.0, 0.0, 1.0, 1.0], np.float32)
_QUAD = np.array([0, 1, 2, 0, 2, 3], np.int32)


class QuadBatch:
    def __init__(self, capacity: int):
        self.capacity = max(1, int(capacity))
        self.vertices = np.zeros(self.capacity * 4, VERTEX)
        self.indices = (np.arange(self.capacity, dtype=np.int32)[:, None] * 4 + _QUAD).ravel()
        quads = self.vertices.reshape(self.capacity, 4)
        quads["u"][:] = _CORNER_U
        quads["v"][:] = _CORNER_V
        self._quads = quads
        self.count = 0

    def _fit(self, n: int) -> int:
        return max(0, min(int(n), self.capacity))

    @staticmethod
    def _vec(value, n: int) -> np.ndarray:
        """A scalar or per-quad array as a float32 (n,) array."""
        value = np.asarray(value, np.float32)
        return np.broadcast_to(value if value.ndim == 0 else value[:n], (n,))

    def _colors(self, n: int, rgb, alpha) -> None:
        q = self._quads[:n]
        rgb = np.asarray(rgb)
        if rgb.ndim == 1:
            q["r"], q["g"], q["b"] = int(rgb[0]), int(rgb[1]), int(rgb[2])
        else:
            rgb = np.clip(rgb[:n], 0, 255).astype(np.uint8)
            q["r"] = rgb[:, 0:1]
            q["g"] = rgb[:, 1:2]
            q["b"] = rgb[:, 2:3]
        alpha = np.asarray(alpha)
        if alpha.ndim == 0:
            q["a"] = int(np.clip(alpha, 0, 255))
        else:
            q["a"] = np.clip(alpha[:n], 0, 255).astype(np.uint8)[:, None]

    def sprites(self, x, y, half_w, half_h, rgb, alpha) -> int:
        """Axis-aligned quads centred on (x, y)."""
        n = self._fit(len(x))
        q = self._quads[:n]
        x = np.asarray(x[:n], np.float32)[:, None]
        y = np.asarray(y[:n], np.float32)[:, None]
        hw = self._vec(half_w, n)[:, None]
        hh = self._vec(half_h, n)[:, None]
        q["x"] = x + hw * (2.0 * _CORNER_U - 1.0)
        q["y"] = y + hh * (2.0 * _CORNER_V - 1.0)
        self._colors(n, rgb, alpha)
        self.count = n
        return n

    def streaks(self, head_x, head_y, angle, length, half_w, rgb, alpha) -> int:
        """Quads from a tail to a head along ``angle`` (radians); u runs tail -> head."""
        n = self._fit(len(head_x))
        q = self._quads[:n]
        hx = np.asarray(head_x[:n], np.float32)
        hy = np.asarray(head_y[:n], np.float32)
        a = np.asarray(angle[:n], np.float32)
        length = self._vec(length, n)
        hw = self._vec(half_w, n)
        dx, dy = np.cos(a), np.sin(a)
        tx, ty = hx - dx * length, hy - dy * length
        nx, ny = -dy * hw, dx * hw
        # corners: tail-top, head-top, head-bottom, tail-bottom
        q["x"] = np.stack([tx + nx, hx + nx, hx - nx, tx - nx], axis=1)
        q["y"] = np.stack([ty + ny, hy + ny, hy - ny, ty - ny], axis=1)
        self._colors(n, rgb, alpha)
        self.count = n
        return n

    def draw(self, canvas: Canvas, texture: Texture, blend: int = BLEND, count: int = -1) -> None:
        n = self.count if count < 0 else self._fit(count)
        if n:
            canvas.geometry(texture, self.vertices, n * 4, self.indices, n * 6, blend)


class Mesh:
    """A fixed triangle topology whose vertex positions and colours change per frame."""

    def __init__(self, vertex_count: int, indices: np.ndarray):
        self.vertices = np.zeros(int(vertex_count), VERTEX)
        self.indices = np.ascontiguousarray(indices, np.int32)

    @classmethod
    def strip_grid(cls, columns: int, rows: int) -> "Mesh":
        """(columns+1) x (rows+1) vertices, two triangles per cell; vertex (c, r) at r*(columns+1)+c."""
        cols, rws = int(columns), int(rows)
        stride = cols + 1
        c = np.arange(cols, dtype=np.int32)
        r = np.arange(rws, dtype=np.int32)[:, None]
        top_left = r * stride + c
        cells = np.stack([top_left, top_left + 1, top_left + stride + 1,
                          top_left, top_left + stride + 1, top_left + stride], axis=-1)
        mesh = cls(stride * (rws + 1), cells.reshape(-1))
        mesh.columns, mesh.rows = cols, rws
        return mesh

    def grid(self, field: str) -> np.ndarray:
        """A (rows+1, columns+1) view of one vertex field."""
        return self.vertices[field].reshape(self.rows + 1, self.columns + 1)

    def draw(self, canvas: Canvas, texture=None, blend: int = BLEND) -> None:
        canvas.geometry(texture, self.vertices, len(self.vertices), self.indices,
                        len(self.indices), blend)
