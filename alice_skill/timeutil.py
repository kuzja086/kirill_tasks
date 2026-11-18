"""Время навыка: «сегодня» считается по Екатеринбургу.

Екатеринбург живёт в UTC+5 и с 2014 года не переходит на летнее время,
поэтому фиксированного смещения достаточно и не нужна база tzdata
(на Windows и в Cloud Functions её может не быть).
"""

from __future__ import annotations

import datetime as dt

# Екатеринбург: UTC+5, без перехода на летнее время.
SKILL_TIMEZONE = dt.timezone(dt.timedelta(hours=5), name="YEKT")


def today_in_skill_timezone() -> dt.date:
    """Сегодняшняя дата по времени навыка (Екатеринбург, UTC+5)."""
    return dt.datetime.now(SKILL_TIMEZONE).date()
