from datetime import date, timedelta

import pytest

from app.services.sm2 import apply_sm2


def test_new_card_q1():
    result = apply_sm2(q=1, interval=1, ease_factor=2.5, repetition=0, today=date(2026, 7, 26))
    assert result.interval == 1
    assert result.repetition == 0
    assert result.ease_factor == pytest.approx(2.5 + (0.1 - 4 * (0.08 + 4 * 0.02)))
    assert result.ease_factor >= 1.3
    assert result.next_review == date(2026, 7, 27)


def test_new_card_q3():
    result = apply_sm2(q=3, interval=1, ease_factor=2.5, repetition=0, today=date(2026, 7, 26))
    assert result.interval == 1
    assert result.repetition == 1
    assert result.ease_factor == pytest.approx(2.5 + (0.1 - 2 * (0.08 + 2 * 0.02)))
    assert result.next_review == date(2026, 7, 27)


def test_new_card_q5():
    result = apply_sm2(q=5, interval=1, ease_factor=2.5, repetition=0, today=date(2026, 7, 26))
    assert result.interval == 1
    assert result.repetition == 1
    assert result.ease_factor == pytest.approx(2.6)
    assert result.next_review == date(2026, 7, 27)


def test_second_success():
    result = apply_sm2(q=5, interval=1, ease_factor=2.6, repetition=1, today=date(2026, 7, 26))
    assert result.interval == 6
    assert result.repetition == 2
    assert result.next_review == date(2026, 8, 1)


def test_subsequent_success_uses_old_ease_factor():
    result = apply_sm2(q=5, interval=6, ease_factor=2.5, repetition=2, today=date(2026, 7, 26))
    assert result.interval == 15
    assert result.repetition == 3
    assert result.ease_factor == pytest.approx(2.6)
    assert result.next_review == date(2026, 7, 26) + timedelta(days=15)


def test_reset_after_bad_answer():
    result = apply_sm2(q=1, interval=15, ease_factor=2.6, repetition=3, today=date(2026, 7, 26))
    assert result.interval == 1
    assert result.repetition == 0
    assert result.next_review == date(2026, 7, 27)


def test_ease_factor_minimum():
    result = apply_sm2(q=1, interval=1, ease_factor=1.3, repetition=0, today=date(2026, 7, 26))
    assert result.ease_factor >= 1.3
    assert result.ease_factor == 1.3


def test_invalid_q():
    with pytest.raises(ValueError):
        apply_sm2(q=4, interval=1, ease_factor=2.5, repetition=0)
