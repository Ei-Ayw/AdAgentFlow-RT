"""Workload scheduler helpers."""
from __future__ import annotations

from typing import Iterable, Iterator, TypeVar

T = TypeVar("T")


def round_robin(items: Iterable[T]) -> Iterator[T]:
    yield from items
