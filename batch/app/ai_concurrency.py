"""LLM 呼び出しの軽度並列ヘルパー（BAT-002 / BAT-004 共用）。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def resolve_ai_concurrency(value: int | None, *, default: int = 3) -> int:
    """1〜8 にクランプした並列度を返す。

    LLM 呼び出しはネットワーク I/O 待ちが主で、ローカル CPU より API レート制限がボトルネックになりやすい。
    """
    try:
        n = int(value) if value is not None else default
    except (TypeError, ValueError):
        n = default
    return max(1, min(8, n))


_UNSET = object()


def map_parallel(
    items: list[T],
    fn: Callable[[T], R],
    *,
    concurrency: int,
) -> list[R]:
    """items の順序を保ったまま fn を軽度並列実行する。

    concurrency=1 または件数 0/1 のときは直列。
    """
    if not items:
        return []
    workers = resolve_ai_concurrency(concurrency)
    if workers <= 1 or len(items) == 1:
        return [fn(item) for item in items]

    workers = min(workers, len(items))
    # インデックスで埋めて入力順を維持する（None 戻り値と未完了を区別する）
    slot: list[R | object] = [_UNSET] * len(items)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_index = {pool.submit(fn, item): idx for idx, item in enumerate(items)}
        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            slot[idx] = future.result()
    out: list[R] = []
    for value in slot:
        if value is _UNSET:
            raise RuntimeError("parallel map left an empty result slot")
        out.append(value)  # type: ignore[arg-type]
    return out
