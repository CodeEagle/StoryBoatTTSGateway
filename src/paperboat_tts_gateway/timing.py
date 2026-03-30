from __future__ import annotations

import re

from .api_models import WordTiming

WORD_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def tokenize_for_timings(text: str) -> list[str]:
    return WORD_RE.findall(text)


def estimate_word_timings(text: str, duration_ms: int) -> list[WordTiming]:
    tokens = tokenize_for_timings(text)
    if not tokens:
        return []

    # Prefer slightly longer slices for longer words without starving punctuation.
    weights = [max(1, sum(2 if char.isalnum() else 1 for char in token)) for token in tokens]
    total_weight = sum(weights)

    timings: list[WordTiming] = []
    cursor = 0
    for index, (token, weight) in enumerate(zip(tokens, weights, strict=False)):
        start_ms = cursor
        if index == len(tokens) - 1:
            end_ms = duration_ms
        else:
            slice_ms = max(1, round(duration_ms * (weight / total_weight)))
            end_ms = min(duration_ms, cursor + slice_ms)
        timings.append(WordTiming(text=token, start_ms=start_ms, end_ms=end_ms))
        cursor = end_ms

    return timings
