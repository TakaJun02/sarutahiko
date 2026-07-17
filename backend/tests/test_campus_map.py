from __future__ import annotations

from app.agent.campus_map import (
    EDGES,
    NODES,
    ResolvedLocation,
    build_route_map_payload,
    find_shortest_route,
    generate_route_steps,
    resolve_location,
)


def test_campus_map_has_only_the_nine_specified_nodes() -> None:
    assert set(NODES) == {
        "g1",
        "g2",
        "d",
        "k",
        "cafeteria",
        "j",
        "gym",
        "o_bakuro",
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
        ("E11", "g1", "o_bakuro", None, 10, "walk"),
        ("E12", "o_bakuro", "o_minami", None, 15, "walk"),
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


def test_minutes_are_displayed_only_when_the_source_edge_has_minutes() -> None:
    origin = resolve_location("学部棟Ⅰ")
    destination = resolve_location("暴露試験場")
    assert origin is not None and destination is not None

    payload = build_route_map_payload(origin, destination)

    assert payload["path"]["edges"] == ["E11"]
    assert any("徒歩 約10分" in step for step in payload["steps"])
    assert not any("徒歩 約3分" in step or "徒歩 約5分" in step for step in payload["steps"])
