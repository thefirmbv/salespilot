"""Parse free-form Dutch text describing a weekly schedule into
RecurrenceTemplate rows.

Examples that should work:
  "Elke maandag 9:00-9:30 standup"
  "ma di wo do vr 8:30 ochtendcheck 15min"
  "Dinsdag en donderdag 13-14 deep work"
  "Vrijdag 16:00 weekreview 30 minuten"
  "Iedere ochtend 8u-9u dagstart"

Strategy: best-effort regex-based parser. Each input line becomes one
template. Unparseable lines are reported back so the user can fix them
without losing the rest. This is deliberately forgiving -- ADHD-Lisa
should be able to type fast and not battle with strict syntax.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import time


# Mon=1, Tue=2, ..., Sun=64
WEEKDAY_BITS = {
    0: 1, 1: 2, 2: 4, 3: 8, 4: 16, 5: 32, 6: 64,
}

WEEKDAY_NAMES: dict[str, int] = {
    "maandag": 0, "dinsdag": 1, "woensdag": 2, "donderdag": 3,
    "vrijdag": 4, "zaterdag": 5, "zondag": 6,
    "ma": 0, "di": 1, "wo": 2, "do": 3, "vr": 4, "za": 5, "zo": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}

DAY_BUNDLES: dict[str, list[int]] = {
    "doordeweeks": [0, 1, 2, 3, 4],
    "weekdagen": [0, 1, 2, 3, 4],
    "elke werkdag": [0, 1, 2, 3, 4],
    "werkdagen": [0, 1, 2, 3, 4],
    "weekend": [5, 6],
    "weekenden": [5, 6],
    "elke dag": [0, 1, 2, 3, 4, 5, 6],
    "iedere dag": [0, 1, 2, 3, 4, 5, 6],
    "dagelijks": [0, 1, 2, 3, 4, 5, 6],
}

TIME_OF_DAY = {
    "ochtend": (time(9, 0), time(12, 0)),
    "middag":  (time(13, 0), time(17, 0)),
    "avond":   (time(19, 0), time(21, 0)),
    "lunch":   (time(12, 0), time(13, 0)),
}

KIND_KEYWORDS = {
    "focus": "focus", "deep work": "focus", "concentratie": "focus",
    "standup": "meeting", "stand-up": "meeting", "overleg": "meeting",
    "meeting": "meeting", "1:1": "meeting", "1-op-1": "meeting",
    "klant": "client", "klanten": "client", "client": "client",
    "admin": "admin", "administratie": "admin", "mail": "admin",
    "pauze": "break", "lunch": "break", "koffie": "break",
    "review": "admin", "weekreview": "admin", "dagstart": "admin",
    "sport": "personal", "wandelen": "personal", "ophalen": "personal",
}


_TIME_RE = re.compile(
    r"\b("
    r"(?P<h1>\d{1,2})"
    r"(?:[:.uU](?P<m1>\d{2}))?"
    r"\s*[-tot\u2013\u2014]+\s*"
    r"(?P<h2>\d{1,2})"
    r"(?:[:.uU](?P<m2>\d{2}))?"
    r"\b|"
    r"(?P<sh>\d{1,2})"
    r"(?:[:.uU](?P<sm>\d{2}))?"
    r"\b)"
)

_DUR_RE = re.compile(
    r"(?:(?P<hours>\d+(?:[.,]\d+)?)\s*(?:uur|u\b|h\b)"
    r"|(?P<mins>\d{1,3})\s*(?:minuten|min\b|m\b))"
)


@dataclass
class ParsedTemplate:
    title: str
    weekdays: list[int]
    start_time: time
    end_time: time
    kind: str
    notes: str | None = None


@dataclass
class ParseResult:
    templates: list[ParsedTemplate] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)


def _detect_weekdays(line_l: str) -> tuple[list[int], str]:
    days: set[int] = set()
    cleaned = line_l

    for kw, day_list in sorted(DAY_BUNDLES.items(), key=lambda kv: -len(kv[0])):
        if kw in cleaned:
            for d in day_list:
                days.add(d)
            cleaned = cleaned.replace(kw, " ")

    for name, idx in sorted(WEEKDAY_NAMES.items(), key=lambda kv: -len(kv[0])):
        pattern = re.compile(rf"\b{re.escape(name)}s?\b")
        if pattern.search(cleaned):
            days.add(idx)
            cleaned = pattern.sub(" ", cleaned)

    return sorted(days), cleaned


def _detect_times(line_l: str) -> tuple[time | None, time | None, str]:
    m = _TIME_RE.search(line_l)
    if m is None:
        return None, None, line_l
    cleaned = (line_l[: m.start()] + " " + line_l[m.end():]).strip()
    g = m.groupdict()
    if g.get("h1"):
        h1 = int(g["h1"]); m1 = int(g["m1"] or 0)
        h2 = int(g["h2"]); m2 = int(g["m2"] or 0)
        try:
            return time(h1, m1), time(h2, m2), cleaned
        except ValueError:
            return None, None, cleaned
    elif g.get("sh"):
        sh = int(g["sh"]); sm = int(g["sm"] or 0)
        try:
            st = time(sh, sm)
        except ValueError:
            return None, None, cleaned
        dm = _DUR_RE.search(cleaned)
        if dm:
            if dm.group("mins"):
                mins = int(dm.group("mins"))
            else:
                h = float(dm.group("hours").replace(",", "."))
                mins = int(h * 60)
            end_total_min = sh * 60 + sm + mins
            eh, em = divmod(end_total_min, 60)
            if 0 <= eh < 24:
                cleaned = (cleaned[:dm.start()] + " " + cleaned[dm.end():]).strip()
                return st, time(eh, em), cleaned
        eh = (sh + 1) % 24
        return st, time(eh, sm), cleaned
    return None, None, line_l


def _detect_time_of_day(line_l: str) -> tuple[time | None, time | None, str]:
    for kw, (st, et) in TIME_OF_DAY.items():
        if kw in line_l:
            cleaned = line_l.replace(kw, " ").strip()
            return st, et, cleaned
    return None, None, line_l


def _classify_kind(title: str) -> str:
    t = title.lower()
    for kw, kind in KIND_KEYWORDS.items():
        if kw in t:
            return kind
    return "other"


def _strip_filler(s: str) -> str:
    s = s.strip()
    s = re.sub(
        r"^(elke|iedere|elk|elken|op|om|voor|tijdens|in|gedurende|altijd)\b\s*",
        "", s, flags=re.IGNORECASE,
    )
    # Day-name conjunctions left over: "en", "of", "of/en", "&", "+"
    s = re.sub(r"\b(en|of|\&|\+)\b", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"[\-,;]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(" -.:;,")
    # Strip orphan connective at start ("en deep work" -> "deep work")
    s = re.sub(r"^(en|of)\s+", "", s, flags=re.IGNORECASE)
    return s


def parse_schedule_text(text: str) -> ParseResult:
    result = ParseResult()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[\-\*\u2022\d\.\)]+\s*", "", line)
        if not line:
            continue

        line_l = line.lower()
        weekdays, cleaned = _detect_weekdays(line_l)
        if not weekdays:
            result.errors.append((raw_line, "geen dag(en) herkend"))
            continue

        start_t, end_t, cleaned = _detect_times(cleaned)
        if start_t is None:
            start_t, end_t, cleaned = _detect_time_of_day(cleaned)
        if start_t is None or end_t is None:
            result.errors.append((raw_line, "geen tijd herkend"))
            continue

        title_lower = _strip_filler(cleaned)
        if not title_lower:
            result.errors.append((raw_line, "geen titel"))
            continue

        title = title_lower
        m = re.search(re.escape(title_lower), line, re.IGNORECASE)
        if m:
            title = line[m.start(): m.end()]
        title = title.strip(" -.:;,").strip()
        if not title:
            title = title_lower

        kind = _classify_kind(title)

        result.templates.append(ParsedTemplate(
            title=title,
            weekdays=weekdays,
            start_time=start_t,
            end_time=end_t,
            kind=kind,
        ))
    return result


def weekdays_to_bitmask(weekdays: list[int]) -> int:
    out = 0
    for d in weekdays:
        out |= WEEKDAY_BITS[d]
    return out


def bitmask_to_weekdays(mask: int) -> list[int]:
    return [d for d in range(7) if mask & WEEKDAY_BITS[d]]
