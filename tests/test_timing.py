from paperboat_tts_gateway.timing import estimate_word_timings, tokenize_for_timings


def test_tokenize_for_timings_keeps_punctuation() -> None:
    assert tokenize_for_timings("Hello, world!") == ["Hello", ",", "world", "!"]


def test_estimate_word_timings_cover_full_duration() -> None:
    timings = estimate_word_timings("Hello world", 1000)
    assert timings[0].start_ms == 0
    assert timings[-1].end_ms == 1000
    assert all(item.end_ms >= item.start_ms for item in timings)
