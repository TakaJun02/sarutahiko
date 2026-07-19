from __future__ import annotations

import json
from pathlib import Path

from app.agent.campus_map import (
    EDGES,
    NODES,
    ORIGIN_SELECT_LABELS,
    ResolvedLocation,
    build_route_map_payload,
    find_shortest_route,
    generate_route_steps,
    resolve_location,
)


EXPECTED_PLACES = {
    "電子材料・物性工学研究室": {"node": "g1", "room": "GI-403", "floor": 4},
    "ソフトマター・デバイス応用研究室": {"node": "g1", "room": "GI-404", "floor": 4},
    "テラヘルツ応用工学": {"node": "g1", "room": "GI-404", "floor": 4},
    "通信システム工学研究室": {"node": "d", "room": "D201", "floor": 2},
    "人工生体機構研究室": {"node": "d", "room": "D202", "floor": 2},
    "ロボットシステム研究室": {"node": "g2", "room": "GII-314", "floor": 3},
    "ソフトメカニクス研究室": {"node": "g2", "room": "GII-316", "floor": 3},
    "インテリジェントシステム研究室": {"node": "g2", "room": "GII-317", "floor": 3},
    "制御システム研究室": {"node": "g2", "room": "GII-413", "floor": 4},
    "システムデザイン研究室": {"node": "g1", "room": "GI611", "floor": 6},
    "情報ネットワーク研究室": {"node": "g1", "room": "GI512", "floor": 5},
    "幾何情報処理研究室": {"node": "g1", "room": "GI201", "floor": 2},
    "画像情報処理研究室": {"node": "g1", "room": "GI324", "floor": 3},
    "音情報処理研究室": {"node": "d", "room": "D407"},
    "共用実験室、建築構造・材料実験室、構造学・材料学": {
        "node": "j",
        "room": "J113、J106",
    },
    "計画学・設計教育委員会、計画学": {
        "node": "g1",
        "room": "G1アトリウム",
        "floor": 2,
    },
    "環境学・材料学": {"node": "o_minami", "room": "公開ゾーンO（南側多目的広場）"},
    "計画数理統計学研究室": {"node": "g2", "room": "GII517"},
    "先端ビジネス会計研究室": {"node": "g2", "room": "GII609"},
    "サイバーフィジカルシステム研究室": {"node": "d", "room": "D404"},
    "CPS研": {"node": "d", "room": "D404"},
    "山口研究室": {"node": "d", "room": "D404"},
    "応用経済学研究室": {"node": "g2", "room": "GII516"},
    "経営数理解析研究室": {"node": "g2", "room": "GII513"},
    "経営システム工学科": {"node": "k", "room": "K325"},
}


def _location_data() -> dict:
    path = Path(__file__).parents[1] / "app" / "agent" / "locations.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_campus_map_has_only_the_eight_real_map_nodes() -> None:
    assert set(NODES) == {
        "g1",
        "g2",
        "d",
        "k",
        "cafeteria",
        "j",
        "gym",
        "o_minami",
    }


def test_campus_map_edges_are_an_exact_transcription_of_the_spec() -> None:
    assert [
        (edge.id, edge.start, edge.end, edge.floor, edge.minutes, edge.kind)
        for edge in EDGES
    ] == [
        ("E1", "g1", "d", 4, None, "connector"),
        ("E2", "g1", "d", 2, None, "connector"),
        ("E3", "g2", "d", 3, None, "connector"),
        ("E4", "g2", "d", 2, None, "connector"),
        ("E5", "k", "g1", 2, None, "indoor"),
        ("E6a", "g1", "cafeteria", None, None, "front"),
        ("E6b", "g2", "cafeteria", None, None, "front"),
        ("E6c", "g1", "g2", None, None, "front"),
        ("E7", "cafeteria", "gym", None, None, "path"),
        ("E8", "k", "cafeteria", None, 10, "walk"),
        ("E9", "k", "j", None, 15, "walk"),
        ("E10", "j", "g1", None, 10, "walk"),
        ("E13", "o_minami", "k", None, 15, "walk"),
        ("E14", "o_minami", "cafeteria", None, 10, "walk"),
        ("E15", "g1", "o_minami", None, 15, "walk"),
    ]


def test_resolver_uses_nfkc_casefold_and_preserves_unknown_floor() -> None:
    assert resolve_location("ｇｉ５１２") == ResolvedLocation(
        node="g1",
        label="学部棟Ⅰ",
        room="GI512",
        floor=5,
    )
    assert resolve_location("d404") == ResolvedLocation(
        node="d",
        label="大学院棟",
        room="D404",
        floor=None,
    )
    assert resolve_location("知らない部屋") is None
    assert resolve_location("食堂") == ResolvedLocation(
        node="cafeteria",
        label="カフェテリア（食堂）",
        floor=None,
    )


def test_resolver_accepts_the_exact_labels_sent_by_map_taps() -> None:
    assert resolve_location("カフェテリア（食堂）") == ResolvedLocation(
        node="cafeteria",
        label="カフェテリア（食堂）",
    )
    assert resolve_location("共通施設棟（総合受付）") == ResolvedLocation(
        node="k",
        label="共通施設棟（総合受付）",
        floor=1,
    )


def test_resolver_matches_places_and_deterministic_fallback_forms() -> None:
    expected = ResolvedLocation(
        node="d",
        label="大学院棟",
        room="D404",
        floor=None,
    )
    assert resolve_location("サイバーフィジカルシステム研究室") == expected
    assert resolve_location("CPS研") == expected
    assert resolve_location("山口研究室") == expected
    assert resolve_location("サイバーフィジカルシステム研究室（CPS研、山口研究室）") == expected
    assert resolve_location("研究室案内（ＣＰＳ研）") == expected
    assert resolve_location("CPS研まで") == expected
    assert resolve_location("CPS研へ") == expected
    assert resolve_location("CPS研に") == expected
    assert resolve_location("CPS研までへ") is None

    network = resolve_location("情報ネットワーク研究室")
    assert network == ResolvedLocation(
        node="g1",
        label="学部棟Ⅰ",
        room="GI512",
        floor=5,
    )
    assert network is not None
    assert network.resolved_name == "情報ネットワーク研究室"


def test_places_are_an_exact_transcription_of_location_index_eligible_names() -> None:
    assert _location_data()["places"] == EXPECTED_PLACES


def test_every_place_references_a_real_node_and_consistent_room() -> None:
    location_data = _location_data()
    rooms = location_data["rooms"]

    for place_name, place in location_data["places"].items():
        assert place["node"] in NODES, place_name
        room = place.get("room")
        if room is None:
            assert "floor" not in place, place_name
            continue
        assert room in rooms, place_name
        assert rooms[room]["node"] == place["node"], place_name
        if "floor" in rooms[room]:
            assert place.get("floor") == rooms[room]["floor"], place_name
        else:
            assert "floor" not in place, place_name
        resolved = resolve_location(place_name)
        assert resolved is not None, place_name
        assert resolved.node == place["node"], place_name
        assert resolved.room == room, place_name
        assert resolved.floor == place.get("floor"), place_name


def test_multiple_node_and_removed_map_names_are_not_registered_as_places() -> None:
    places = _location_data()["places"]
    assert "自然エネルギー応用工学研究室" not in places
    assert "知能情報処理研究室" not in places
    assert "情報工学科" not in places
    assert "材料学" not in places
    assert resolve_location("自然エネルギー応用工学研究室") is None
    assert resolve_location("知能情報処理研究室") is None
    assert resolve_location("情報工学科") is None


def test_origin_select_labels_match_all_nodes_and_resolve_as_aliases() -> None:
    assert set(ORIGIN_SELECT_LABELS) == set(NODES)
    for node_id, label in ORIGIN_SELECT_LABELS.items():
        resolved = resolve_location(label)
        assert resolved is not None
        assert resolved.node == node_id


def test_every_real_map_node_pair_has_a_route() -> None:
    for origin_node in NODES:
        for destination_node in NODES:
            route = find_shortest_route(origin_node, destination_node)
            assert route.nodes[0] == origin_node
            assert route.nodes[-1] == destination_node


def test_dijkstra_prefers_connector_matching_known_destination_floor() -> None:
    route = find_shortest_route("cafeteria", "d", destination_floor=4)
    assert route.nodes == ("cafeteria", "g1", "d")
    assert route.edges == ("E6a", "E1")


def test_dijkstra_prefers_entry_floor_when_destination_floor_is_unknown() -> None:
    route = find_shortest_route("cafeteria", "d")
    assert route.nodes == ("cafeteria", "g1", "d")
    assert route.edges == ("E6a", "E2")


def test_reception_to_g2_uses_frontage_route_not_two_connectors() -> None:
    route = find_shortest_route("k", "g2")
    assert route.nodes == ("k", "g1", "g2")
    assert route.edges == ("E5", "E6c")


def test_route_steps_include_ground_floor_vertical_move_and_connector() -> None:
    origin = resolve_location("食堂")
    destination = resolve_location("D414")
    assert origin is not None and destination is not None

    payload = build_route_map_payload(origin, destination)

    assert payload["path"] == {
        "nodes": ["cafeteria", "g1", "d"],
        "edges": ["E6a", "E1"],
    }
    joined = "\n".join(payload["steps"])
    assert "学部棟Ⅰは 2階が地上・2階から入る" in joined
    assert "エレベーターまたは階段で 4階へ" in joined
    assert "4階の連絡通路" in joined
    assert payload["steps"][-1] == "D414（4階）へ"


def test_destination_on_another_floor_keeps_vertical_arrival_step() -> None:
    origin = resolve_location("食堂")
    destination = resolve_location("GI512")
    assert origin is not None and destination is not None

    payload = build_route_map_payload(origin, destination)

    assert payload["steps"][-1] == "エレベーターまたは階段で 5階へ → GI512"


def test_unknown_room_floor_is_not_inferred_in_steps() -> None:
    origin = resolve_location("食堂")
    destination = resolve_location("D404")
    assert origin is not None and destination is not None

    payload = build_route_map_payload(origin, destination)

    assert payload["destination"]["floor"] is None
    assert payload["path"]["edges"] == ["E6a", "E2"]
    assert payload["steps"][-1] == "D404 の階は館内表示・当日スタッフでご確認ください"
    assert not any("4階へ → D404" in step for step in payload["steps"])


def test_reception_to_south_multipurpose_area_uses_e13() -> None:
    origin = resolve_location("総合受付")
    destination = resolve_location("南側多目的広場")
    assert origin is not None and destination is not None

    payload = build_route_map_payload(origin, destination)

    assert payload["path"]["edges"] == ["E13"]
    assert any("徒歩 約15分" in step for step in payload["steps"])
    assert not any("徒歩 約3分" in step or "徒歩 約5分" in step for step in payload["steps"])


def test_exposure_test_site_is_not_resolved_for_map_cards() -> None:
    assert resolve_location("暴露試験場") is None
    assert resolve_location("公開ゾーンO（暴露試験場）") is None
