#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
from pathlib import Path


def unfold(lines: list[str]) -> list[str]:
    result: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t")) and result:
            result[-1] += line[1:]
        else:
            result.append(line)
    return result


def validate(path: Path) -> int:
    raw_bytes = path.read_bytes()
    if not raw_bytes.endswith(b"\r\n") or b"\n" in raw_bytes.replace(b"\r\n", b""):
        print(f"{path}: ICS must use CRLF line endings and end with CRLF", file=sys.stderr)
        return 1

    raw = raw_bytes.decode("utf-8")
    lines = unfold(raw.splitlines())
    if lines[0] != "BEGIN:VCALENDAR" or lines[-1] != "END:VCALENDAR":
        print(f"{path}: ICS must start with BEGIN:VCALENDAR and end with END:VCALENDAR", file=sys.stderr)
        return 1

    stack: list[str] = []
    uids: set[str] = set()
    event_count = 0

    for line in lines:
        if line.startswith("BEGIN:"):
            stack.append(line.removeprefix("BEGIN:"))
            if line == "BEGIN:VEVENT":
                event_count += 1
        elif line.startswith("END:"):
            component = line.removeprefix("END:")
            if not stack or stack.pop() != component:
                print(f"Unbalanced component: {line}", file=sys.stderr)
                return 1
        elif line.startswith("UID:"):
            if line in uids:
                print(f"Duplicate {line}", file=sys.stderr)
                return 1
            uids.add(line)

    if stack:
        print(f"Unclosed components: {stack}", file=sys.stderr)
        return 1
    if event_count == 0:
        print("ICS has no events", file=sys.stderr)
        return 1

    print(f"{path}: ICS OK: {event_count} events")
    return 0


def main() -> int:
    paths = [Path(arg) for arg in sys.argv[1:]] or [Path("ru-production-calendar.ics")]
    return max(validate(path) for path in paths)


if __name__ == "__main__":
    sys.exit(main())
