#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate an iCalendar feed with Russian production-calendar holidays.

The script keeps the local JSON data as the source of truth, but can also try
to refresh it from official Government pages before rendering the ICS file.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote


DATA_FILE = Path("ru_prod_calendar_data.json")
OUTPUT_FILE = Path("ru-production-calendar.ics")
CALENDAR_NAME = "Производственный календарь РФ"
UID_DOMAIN = "prod-calendar"

MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

HOLIDAYS = {
    (1, 1): "Новогодние каникулы",
    (1, 2): "Новогодние каникулы",
    (1, 3): "Новогодние каникулы",
    (1, 4): "Новогодние каникулы",
    (1, 5): "Новогодние каникулы",
    (1, 6): "Новогодние каникулы",
    (1, 7): "Рождество Христово",
    (1, 8): "Новогодние каникулы",
    (2, 23): "День защитника Отечества",
    (3, 8): "Международный женский день",
    (5, 1): "Праздник Весны и Труда",
    (5, 9): "День Победы",
    (6, 12): "День России",
    (11, 4): "День народного единства",
}

SHORT_DAY_LABELS = {
    (1, 1): "1 января",
    (1, 2): "2 января",
    (1, 3): "3 января",
    (1, 4): "4 января",
    (1, 5): "5 января",
    (1, 6): "6 января",
    (1, 7): "7 января",
    (1, 8): "8 января",
    (2, 23): "23 февраля",
    (3, 8): "8 марта",
    (5, 1): "1 мая",
    (5, 9): "9 мая",
    (6, 12): "12 июня",
    (11, 4): "4 ноября",
}


@dataclass(frozen=True)
class Transfer:
    source_day: date
    target_day: date


def escape_ics_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold_ics_line(line: str) -> list[str]:
    """Fold long iCalendar lines at 75 octets without splitting UTF-8 chars."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return [line]

    folded: list[str] = []
    current = ""
    current_len = 0
    for char in line:
        char_len = len(char.encode("utf-8"))
        limit = 75 if not folded else 74
        if current and current_len + char_len > limit:
            folded.append(current if not folded else f" {current}")
            current = char
            current_len = char_len
        else:
            current += char
            current_len += char_len
    if current:
        folded.append(current if not folded else f" {current}")
    return folded


def date_to_ics(day: date) -> str:
    return day.strftime("%Y%m%d")


def next_day_to_ics(day: date) -> str:
    return (day + timedelta(days=1)).strftime("%Y%m%d")


def iso(day: date) -> str:
    return day.isoformat()


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def parse_iso_day(value: str) -> date:
    return date.fromisoformat(value)


def load_data() -> dict[str, Any]:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def save_data(data: dict[str, Any]) -> None:
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def request_text(url: str, timeout: int = 20) -> str:
    result = subprocess.run(
        [
            "curl",
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--max-time",
            str(timeout),
            "--user-agent",
            (
                "Mozilla/5.0 (compatible; ru-production-calendar/1.0; "
                "+https://github.com/akrenev-droid/prod-calendar)"
            ),
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout + 3,
    )
    return result.stdout


def html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def source_urls(year_data: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for item in year_data.get("source", []):
        urls.extend(re.findall(r"https?://government\.ru/\S+|government\.ru/\S+", item))
    return [url if url.startswith("http") else f"https://{url}" for url in urls]


def discover_government_pages(year: int) -> list[str]:
    query = quote(f"О переносе выходных дней в {year} году")
    search_urls = [
        f"https://government.ru/search/?q={query}",
        f"https://government.ru/docs/?q={query}",
        f"https://government.ru/docs/all/?q={query}",
    ]
    found: list[str] = []
    for url in search_urls:
        try:
            page = request_text(url, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        for match in re.findall(r'href="(/docs/(?:all/)?\d+/)"', page):
            full_url = f"https://government.ru{match}"
            if full_url not in found:
                found.append(full_url)
    return found


def parse_transfer_day(year: int, day: str, month: str) -> date:
    return date(year, MONTHS[month.lower()], int(day))


def parse_transfers(text: str, year: int) -> list[Transfer]:
    pattern = re.compile(
        r"с\s+(?:понедельника|вторника|среды|четверга|пятницы|субботы|воскресенья)"
        r"\s+(\d{1,2})\s+([а-яё]+)\s+на\s+"
        r"(?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)"
        r"\s+(\d{1,2})\s+([а-яё]+)",
        re.IGNORECASE,
    )
    return [
        Transfer(
            source_day=parse_transfer_day(year, source_day, source_month),
            target_day=parse_transfer_day(year, target_day, target_month),
        )
        for source_day, source_month, target_day, target_month in pattern.findall(text)
    ]


def extract_resolution(text: str) -> str | None:
    match = re.search(
        r"(Постановление(?: Правительства(?: Российской Федерации)?)?"
        r" от \d{1,2} [а-яё]+ \d{4} года №\s*\d+)",
        text,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def official_holidays(year: int) -> dict[date, str]:
    return {date(year, month, day): name for (month, day), name in HOLIDAYS.items()}


def next_working_day(start: date, non_working: set[date]) -> date:
    candidate = start + timedelta(days=1)
    while is_weekend(candidate) or candidate in non_working:
        candidate += timedelta(days=1)
    return candidate


def calculate_year(year: int, transfers: list[Transfer], source: list[str]) -> dict[str, Any]:
    holidays = official_holidays(year)
    non_working: dict[date, str] = dict(holidays)
    transfer_targets = {transfer.target_day for transfer in transfers}

    for transfer in transfers:
        non_working[transfer.target_day] = (
            f"Выходной: перенос с {transfer.source_day.strftime('%d.%m.%Y')}"
        )

    # Article 112 default: if a holiday outside Jan 1-8 falls on a weekend,
    # the day off moves to the next working day unless the Government sets another date.
    occupied = set(non_working) | transfer_targets
    for holiday_day, holiday_name in sorted(holidays.items()):
        if holiday_day.month == 1 and holiday_day.day <= 8:
            continue
        if is_weekend(holiday_day):
            target = next_working_day(holiday_day, occupied)
            non_working[target] = f"Выходной: перенос с {holiday_day.strftime('%d.%m.%Y')}"
            occupied.add(target)

    short_days: dict[date, str] = {}
    for holiday_day in sorted(holidays):
        candidate = holiday_day - timedelta(days=1)
        if candidate.year == year and not is_weekend(candidate) and candidate not in non_working:
            label = SHORT_DAY_LABELS[(holiday_day.month, holiday_day.day)]
            short_days[candidate] = f"Сокращённый рабочий день перед {label}"

    return {
        "source": source,
        "transfers": [
            {"from": iso(transfer.source_day), "to": iso(transfer.target_day)}
            for transfer in sorted(transfers, key=lambda item: item.target_day)
        ],
        "non_working_days": {
            iso(day): title for day, title in sorted(non_working.items())
        },
        "short_days": {
            iso(day): title for day, title in sorted(short_days.items())
        },
    }


def fetch_official_year(year: int, known_urls: list[str]) -> dict[str, Any] | None:
    for url in known_urls:
        try:
            page = request_text(url, timeout=8)
        except (OSError, subprocess.SubprocessError):
            continue

        text = html_to_text(page)
        if f"переносе выходных дней в {year} году" not in text.lower():
            continue

        transfers = parse_transfers(text, year)
        if not transfers:
            continue

        resolution = extract_resolution(text)
        source = [
            resolution or f"Официальная публикация Правительства РФ о переносе выходных дней в {year} году",
            f"Официальная публикация Правительства РФ: {url}",
        ]
        return calculate_year(year, transfers, source)

    for url in discover_government_pages(year):
        try:
            page = request_text(url, timeout=8)
        except (OSError, subprocess.SubprocessError):
            continue

        text = html_to_text(page)
        if f"переносе выходных дней в {year} году" not in text.lower():
            continue

        transfers = parse_transfers(text, year)
        if not transfers:
            continue

        resolution = extract_resolution(text)
        source = [
            resolution or f"Официальная публикация Правительства РФ о переносе выходных дней в {year} году",
            f"Официальная публикация Правительства РФ: {url}",
        ]
        return calculate_year(year, transfers, source)
    return None


def refresh_data(years: list[int]) -> bool:
    data = load_data()
    changed = False

    for year in years:
        key = str(year)
        refreshed = fetch_official_year(year, source_urls(data.get(key, {})))
        if refreshed is None:
            print(f"Данные за {year}: официальная страница не найдена, оставляю как есть.")
            continue
        if data.get(key) != refreshed:
            data[key] = refreshed
            changed = True
            print(f"Данные за {year}: обновлены из официального источника.")
        else:
            print(f"Данные за {year}: актуальны.")

    if changed:
        save_data(data)
    return changed


def make_event(day: str, title: str, now: str) -> list[str]:
    event_day = parse_iso_day(day)
    stable_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{day}:{title}")
    raw_lines = [
        "BEGIN:VEVENT",
        f"UID:{day}-{stable_id.hex[:12]}@{UID_DOMAIN}",
        f"DTSTAMP:{now}",
        f"DTSTART;VALUE=DATE:{date_to_ics(event_day)}",
        f"DTEND;VALUE=DATE:{next_day_to_ics(event_day)}",
        f"SUMMARY:{escape_ics_text(title)}",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]
    folded: list[str] = []
    for line in raw_lines:
        folded.extend(fold_ics_line(line))
    return folded


def event_title(kind: str, name: str) -> str:
    if kind == "short":
        return "Сокращённый день"
    if name.lower().startswith("выходной: перенос"):
        return "Выходной: перенос"
    if name == "Международный женский день":
        return "Выходной: 8 марта"
    if name == "День защитника Отечества":
        return "Выходной: 23 февраля"
    if name == "Праздник Весны и Труда":
        return "Выходной: 1 мая"
    if name == "День народного единства":
        return "Выходной: 4 ноября"
    return f"Выходной: {name}"


def generate() -> None:
    data = load_data()
    now = "20260101T000000Z"

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Personal RU Production Calendar//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_ics_text(CALENDAR_NAME)}",
        f"NAME:{escape_ics_text(CALENDAR_NAME)}",
        "X-WR-TIMEZONE:Europe/Moscow",
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:PT24H",
    ]

    for year, year_data in sorted(data.items()):
        for day, name in sorted(year_data.get("non_working_days", {}).items()):
            lines.extend(make_event(
                day,
                event_title("non_working", name),
                now,
            ))

        for day, name in sorted(year_data.get("short_days", {}).items()):
            lines.extend(make_event(
                day,
                event_title("short", name),
                now,
            ))

    lines.append("END:VCALENDAR")
    OUTPUT_FILE.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    print(f"Готово: {OUTPUT_FILE.resolve()}")


def default_update_years() -> list[int]:
    today = date.today()
    return [today.year, today.year + 1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--update",
        action="store_true",
        help="Try to refresh JSON data from official Government pages before generating ICS.",
    )
    parser.add_argument(
        "--years",
        nargs="*",
        type=int,
        default=None,
        help="Years to refresh when --update is used. Defaults to current year and next two years.",
    )
    args = parser.parse_args()

    if args.update:
        refresh_data(args.years or default_update_years())

    generate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
