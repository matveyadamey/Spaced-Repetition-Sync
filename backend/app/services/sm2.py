from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class SM2Result:
    interval: int
    ease_factor: float
    repetition: int
    next_review: date


def apply_sm2(
    *,
    q: int,
    interval: int,
    ease_factor: float,
    repetition: int,
    today: date | None = None,
) -> SM2Result:
    """Apply SM-2 spaced repetition algorithm.

    Uses the old ease_factor when computing the new interval.
    """
    if q not in (1, 3, 5):
        raise ValueError(f"Unsupported quality value: {q}")

    if today is None:
        today = date.today()

    old_ease_factor = ease_factor

    if q < 3:
        new_interval = 1
        new_repetition = 0
    elif repetition == 0:
        new_interval = 1
        new_repetition = 1
    elif repetition == 1:
        new_interval = 6
        new_repetition = 2
    else:
        new_interval = max(1, round(interval * old_ease_factor))
        new_repetition = repetition + 1

    new_ease_factor = max(
        1.3,
        old_ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)),
    )

    return SM2Result(
        interval=new_interval,
        ease_factor=new_ease_factor,
        repetition=new_repetition,
        next_review=today + timedelta(days=new_interval),
    )
