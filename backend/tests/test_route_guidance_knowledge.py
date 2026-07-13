from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.lexical import CampusLexicalSearch


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("keywords", "expected_file_ids"),
    [
        (["GI512"], {"event-oc2026-location-index"}),
        (["K321"], {"event-oc2026-location-index", "facility-campus-map"}),
        (["D404"], {"event-oc2026-location-index", "facility-campus-route-graph"}),
        (["総合受付"], {"event-oc2026-location-index", "facility-campus-map", "facility-campus-route-graph"}),
        (["食堂", "どこ"], {"event-oc2026-location-index", "facility-campus-map", "facility-campus-route-graph"}),
        (["食堂", "経路"], {"facility-campus-route-graph"}),
        (["連絡通路"], {"facility-campus-route-graph"}),
        (["D404", "経路"], {"facility-campus-route-graph"}),
        (["食堂", "D404", "経路"], {"facility-campus-route-graph"}),
        (["体育館", "行き方"], {"facility-campus-route-graph"}),
    ],
)
def test_route_guidance_keywords_hit_new_knowledge(
    keywords: list[str],
    expected_file_ids: set[str],
) -> None:
    search = CampusLexicalSearch(REPO_ROOT / "knowledge")

    hit_file_ids = {hit.chunk.file_id for hit in search.grep_sections(keywords)}

    assert expected_file_ids.issubset(hit_file_ids)
