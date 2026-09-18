"""Sparse continuous-layout geometry; unknown rows use the first-page estimate."""
from bisect import bisect_left
from collections.abc import Sequence


class PageRows(Sequence):
    def __init__(self, page_count, facing, step, margin):
        self.page_count = page_count
        self.stride = 2 if facing else 1
        self.count = (page_count + self.stride - 1) // self.stride
        self.step = step
        self.margin = margin
        self.heights = {}
        self._keys = []
        self._prefix = [0]

    def __len__(self):
        return self.count

    def offset(self, row):
        return self.margin + row * self.step + self._prefix[bisect_left(self._keys, row)]

    def __getitem__(self, row):
        if isinstance(row, slice):
            return [self[i] for i in range(*row.indices(self.count))]
        if row < 0:
            row += self.count
        if not 0 <= row < self.count:
            raise IndexError(row)
        first = row * self.stride
        return self.offset(row), list(range(first, min(first + self.stride, self.page_count)))

    def measure(self, row, height):
        if self.heights.get(row) == height:
            return
        self.heights[row] = height
        self._keys = sorted(self.heights)
        self._prefix = [0]
        for key in self._keys:
            self._prefix.append(self._prefix[-1] + self.heights[key] - self.step)

    def row_at(self, y):
        low, high = 0, self.count
        while low < high:
            mid = (low + high) // 2
            if self.offset(mid) <= y:
                low = mid + 1
            else:
                high = mid
        return min(self.count - 1, max(0, low - 1))
