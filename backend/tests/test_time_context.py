from __future__ import annotations

from datetime import datetime, timezone

from app.services.time_context import JST, build_time_context, load_schedule


def test_schedule_loads_verified_open_campus_data() -> None:
    schedule = load_schedule()

    assert schedule.event_date.isoformat() == "2026-07-19"
    assert schedule.open_time.isoformat(timespec="minutes") == "09:30"
    assert schedule.close_time.isoformat(timespec="minutes") == "15:00"
    assert schedule.campus == "本荘キャンパス"
    assert len(schedule.events) > 0


def test_seven_days_before_event_counts_days() -> None:
    context = build_time_context(datetime(2026, 7, 12, 14, 5, tzinfo=JST))

    assert "現在日時: 2026年7月12日（日）14:05" in context
    assert (
        "オープンキャンパス2026（2026年7月19日（日）9:30〜15:00・本荘キャンパス）まであと7日です。"
        in context
    )


def test_day_before_event_says_tomorrow() -> None:
    context = build_time_context(datetime(2026, 7, 18, 9, 0, tzinfo=JST))

    assert "現在日時: 2026年7月18日（土）9:00" in context
    assert "まであと1日（明日）です。" in context


def test_event_day_before_opening_counts_minutes_to_doors() -> None:
    context = build_time_context(datetime(2026, 7, 19, 9, 0, tzinfo=JST))

    assert "本日開催！" in context
    assert "開場（9:30）まであと30分です。" in context


def test_event_day_during_lists_ongoing_and_upcoming_events() -> None:
    context = build_time_context(datetime(2026, 7, 19, 11, 45, tzinfo=JST))

    assert "オープンキャンパス2026は本日開催中です（9:30〜15:00・本荘キャンパス）。" in context
    assert "現在開催中のイベント:" in context
    assert "無料昼食体験（カフェテリア、11:30〜13:30）" in context
    assert "スチューデントカフェ・サークル紹介（ラーニングコモンズ、11:00〜15:00）" in context
    assert "研究室公開（学部棟・特別実験棟・大学院棟ほか、9:30〜15:00）" in context
    assert "まもなく開始するイベント:" in context
    assert "個別進学相談（Kゾーン（共通施設棟）、12:00〜15:00）（あと15分後に開始）" in context
    assert "サークルパフォーマンス（ジャズバンドサークル）（12:10〜12:40）（あと25分後に開始）" in context
    # Bus departing exactly 60 minutes later is still inside the window.
    assert "無料送迎バス 第3便（本荘キャンパス→羽後本荘駅）" in context
    # 合同学科説明会 starts at 13:00 (75 min later) and must not be listed.
    assert "合同学科説明会" not in context


def test_event_day_after_close_thanks_visitors() -> None:
    context = build_time_context(datetime(2026, 7, 19, 15, 0, tzinfo=JST))

    assert "オープンキャンパス2026は本日15:00に終了しました。" in context
    assert "ご来場ありがとうございました" in context


def test_after_event_date_reports_finished() -> None:
    context = build_time_context(datetime(2026, 7, 20, 10, 0, tzinfo=JST))

    assert "オープンキャンパス2026（2026年7月19日（日）・本荘キャンパス）は終了しました。" in context
    assert "お礼" in context


def test_naive_and_utc_datetimes_are_normalized_to_jst() -> None:
    naive = datetime(2026, 7, 19, 10, 0)
    utc = datetime(2026, 7, 19, 1, 0, tzinfo=timezone.utc)

    assert build_time_context(naive) == build_time_context(utc)
    assert "現在日時: 2026年7月19日（日）10:00" in build_time_context(utc)
