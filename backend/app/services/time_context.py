from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
EVENT_NAME = "オープンキャンパス2026"
UPCOMING_WINDOW_MINUTES = 60
WEEKDAY_LABELS = "月火水木金土日"
SCHEDULE_PATH = Path(__file__).resolve().parents[1] / "data" / "oc2026_schedule.json"


@dataclass(frozen=True)
class ScheduleEvent:
    title: str
    location: str | None
    start: time
    end: time
    note: str | None
    category: str | None


@dataclass(frozen=True)
class EventSchedule:
    event_date: date
    open_time: time
    close_time: time
    campus: str
    events: tuple[ScheduleEvent, ...]


@lru_cache(maxsize=1)
def load_schedule() -> EventSchedule:
    payload = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    events = tuple(
        sorted(
            (
                ScheduleEvent(
                    title=str(entry["title"]),
                    location=entry.get("location") or None,
                    start=time.fromisoformat(entry["start"]),
                    end=time.fromisoformat(entry["end"]),
                    note=entry.get("note") or None,
                    category=entry.get("category") or None,
                )
                for entry in payload.get("events", [])
            ),
            key=lambda event: (event.start, event.end, event.title),
        )
    )
    return EventSchedule(
        event_date=date.fromisoformat(payload["event_date"]),
        open_time=time.fromisoformat(payload["open_time"]),
        close_time=time.fromisoformat(payload["close_time"]),
        campus=str(payload["campus"]),
        events=events,
    )


def build_time_context(now: datetime | None = None) -> str:
    """Build the Japanese time-context block injected into generation prompts.

    All date and minute arithmetic is done here deterministically so the LLM
    never has to compute dates or countdowns by itself (FR-8).
    """
    current = _normalize_now(now)
    lines = [f"現在日時: {_format_datetime(current)}"]
    lines.extend(_phase_lines(current, load_schedule()))
    return "\n".join(lines)


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(JST)
    if now.tzinfo is None:
        return now.replace(tzinfo=JST)
    return now.astimezone(JST)


def _phase_lines(current: datetime, schedule: EventSchedule) -> list[str]:
    open_at = datetime.combine(schedule.event_date, schedule.open_time, tzinfo=JST)
    close_at = datetime.combine(schedule.event_date, schedule.close_time, tzinfo=JST)
    hours_label = f"{_format_time(schedule.open_time)}〜{_format_time(schedule.close_time)}"
    today = current.date()

    if today < schedule.event_date:
        days_left = (schedule.event_date - today).days
        countdown = "あと1日（明日）" if days_left == 1 else f"あと{days_left}日"
        return [
            f"{EVENT_NAME}（{_format_date(schedule.event_date)}{hours_label}・{schedule.campus}）"
            f"まで{countdown}です。"
        ]
    if today > schedule.event_date:
        return [
            f"{EVENT_NAME}（{_format_date(schedule.event_date)}・{schedule.campus}）は終了しました。"
            "来場へのお礼の文脈で使えます。"
        ]
    if current < open_at:
        minutes_left = _minutes_until(current, open_at)
        return [
            f"本日開催！{EVENT_NAME}（{hours_label}・{schedule.campus}）の"
            f"開場（{_format_time(schedule.open_time)}）まであと{minutes_left}分です。"
        ]
    if current >= close_at:
        return [
            f"{EVENT_NAME}は本日{_format_time(schedule.close_time)}に終了しました。"
            "ご来場ありがとうございました。来場へのお礼の文脈で使えます。"
        ]
    return _during_lines(current, schedule, hours_label)


def _during_lines(current: datetime, schedule: EventSchedule, hours_label: str) -> list[str]:
    lines = [f"{EVENT_NAME}は本日開催中です（{hours_label}・{schedule.campus}）。"]
    ongoing: list[ScheduleEvent] = []
    upcoming: list[tuple[ScheduleEvent, int]] = []
    for event in schedule.events:
        start_at = datetime.combine(schedule.event_date, event.start, tzinfo=JST)
        end_at = datetime.combine(schedule.event_date, event.end, tzinfo=JST)
        if start_at <= current < end_at:
            ongoing.append(event)
        elif current < start_at:
            minutes_left = _minutes_until(current, start_at)
            if minutes_left <= UPCOMING_WINDOW_MINUTES:
                upcoming.append((event, minutes_left))
    if ongoing:
        lines.append("現在開催中のイベント:")
        lines.extend(f"- {_format_event(event)}" for event in ongoing)
    if upcoming:
        lines.append("まもなく開始するイベント:")
        lines.extend(
            f"- {_format_event(event)}（あと{minutes_left}分後に開始）"
            for event, minutes_left in upcoming
        )
    if not ongoing and not upcoming:
        lines.append("スケジュール上、現在開催中・開始間近のイベントはありません。")
    return lines


def _format_event(event: ScheduleEvent) -> str:
    time_range = f"{_format_time(event.start)}〜{_format_time(event.end)}"
    place = f"{event.location}、" if event.location else ""
    note = f" ※{event.note}" if event.note else ""
    return f"{event.title}（{place}{time_range}）{note}".rstrip()


def _minutes_until(current: datetime, target: datetime) -> int:
    return max(math.ceil((target - current).total_seconds() / 60), 0)


def _format_datetime(value: datetime) -> str:
    return f"{_format_date(value.date())}{value.hour}:{value.minute:02d}"


def _format_date(value: date) -> str:
    return f"{value.year}年{value.month}月{value.day}日（{WEEKDAY_LABELS[value.weekday()]}）"


def _format_time(value: time) -> str:
    return f"{value.hour}:{value.minute:02d}"
