from __future__ import annotations

import heapq
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.rag.lexical import normalize_text

EdgeKind = Literal["connector", "indoor", "front", "path", "walk"]


@dataclass(frozen=True)
class CampusNode:
    id: str
    label: str
    ground_floor: int | None


@dataclass(frozen=True)
class CampusEdge:
    id: str
    start: str
    end: str
    floor: int | None
    minutes: int | None
    kind: EdgeKind

    @property
    def weight(self) -> int:
        if self.minutes is not None:
            return self.minutes
        return 3 if self.kind in {"connector", "indoor"} else 5

    def other(self, node_id: str) -> str:
        if node_id == self.start:
            return self.end
        if node_id == self.end:
            return self.start
        raise ValueError(f"Node {node_id!r} is not connected to edge {self.id!r}")


@dataclass(frozen=True)
class ResolvedLocation:
    node: str
    label: str
    room: str | None = None
    floor: int | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "node": self.node,
            "label": self.label,
            "room": self.room,
            "floor": self.floor,
        }

    def as_origin_payload(self) -> dict[str, str]:
        return {"node": self.node, "label": self.label}


@dataclass(frozen=True)
class CampusRoute:
    nodes: tuple[str, ...]
    edges: tuple[str, ...]


NODES: dict[str, CampusNode] = {
    "g1": CampusNode("g1", "学部棟Ⅰ", 2),
    "g2": CampusNode("g2", "学部棟Ⅱ", 2),
    "d": CampusNode("d", "大学院棟", 2),
    "k": CampusNode("k", "共通施設棟", 1),
    "cafeteria": CampusNode("cafeteria", "メディア交流棟", 1),
    "j": CampusNode("j", "特別実験棟", 1),
    "gym": CampusNode("gym", "体育館", 1),
    "o_minami": CampusNode("o_minami", "屋外O 南側多目的広場", None),
}

# Labels used when a visitor declares their current position from MapCard.
# Every value is also an alias in locations.json so the synthesized question
# stays on the same deterministic resolver path as a typed location.
ORIGIN_SELECT_LABELS: dict[str, str] = {
    "g1": "学部棟Ⅰ",
    "g2": "学部棟Ⅱ",
    "d": "大学院棟",
    "k": "共通施設棟（総合受付）",
    "cafeteria": "カフェテリア（食堂）",
    "j": "特別実験棟",
    "gym": "体育館",
    "o_minami": "屋外O 南側多目的広場",
}

EDGES: tuple[CampusEdge, ...] = (
    CampusEdge("E1", "g1", "d", 4, None, "connector"),
    CampusEdge("E2", "g1", "d", 2, None, "connector"),
    CampusEdge("E3", "g2", "d", 3, None, "connector"),
    CampusEdge("E4", "g2", "d", 2, None, "connector"),
    CampusEdge("E5", "k", "g1", 2, None, "indoor"),
    CampusEdge("E6a", "g1", "cafeteria", None, None, "front"),
    CampusEdge("E6b", "g2", "cafeteria", None, None, "front"),
    CampusEdge("E6c", "g1", "g2", None, None, "front"),
    CampusEdge("E7", "cafeteria", "gym", None, None, "path"),
    CampusEdge("E8", "k", "cafeteria", None, 10, "walk"),
    CampusEdge("E9", "k", "j", None, 15, "walk"),
    CampusEdge("E10", "j", "g1", None, 10, "walk"),
    CampusEdge("E13", "o_minami", "k", None, 15, "walk"),
    CampusEdge("E14", "o_minami", "cafeteria", None, 10, "walk"),
    CampusEdge("E15", "g1", "o_minami", None, 15, "walk"),
)
EDGE_BY_ID = {edge.id: edge for edge in EDGES}


def _load_location_data() -> dict[str, Any]:
    path = Path(__file__).with_name("locations.json")
    return json.loads(path.read_text(encoding="utf-8"))


_LOCATION_DATA = _load_location_data()
_ROOMS = {normalize_text(key): (key, value) for key, value in _LOCATION_DATA["rooms"].items()}
_ALIASES = {normalize_text(key): value for key, value in _LOCATION_DATA["aliases"].items()}


def resolve_location(expression: str | None) -> ResolvedLocation | None:
    if not isinstance(expression, str) or not expression.strip():
        return None
    key = normalize_text(expression.strip())
    room_entry = _ROOMS.get(key)
    if room_entry is not None:
        room, value = room_entry
        node = NODES[value["node"]]
        return ResolvedLocation(
            node=node.id,
            label=node.label,
            room=room,
            floor=value.get("floor"),
        )
    alias = _ALIASES.get(key)
    if alias is None:
        return None
    return ResolvedLocation(
        node=alias["node"],
        label=alias["label"],
        floor=alias.get("floor"),
    )


def normalize_location_name(value: str) -> str:
    return normalize_text(value.strip())


def find_shortest_route(
    origin_node: str,
    destination_node: str,
    *,
    destination_floor: int | None = None,
) -> CampusRoute:
    if origin_node not in NODES or destination_node not in NODES:
        raise ValueError("Unknown campus map node")
    if origin_node == destination_node:
        return CampusRoute(nodes=(origin_node,), edges=())

    adjacency: dict[str, list[CampusEdge]] = {node_id: [] for node_id in NODES}
    for edge in EDGES:
        adjacency[edge.start].append(edge)
        adjacency[edge.end].append(edge)

    distances = {origin_node: 0}
    previous: dict[str, tuple[str, str]] = {}
    queue: list[tuple[int, int, str]] = [(0, 0, origin_node)]
    sequence = 1

    while queue:
        distance, _, current = heapq.heappop(queue)
        if distance != distances.get(current):
            continue
        if current == destination_node:
            break
        ordered_edges = sorted(
            adjacency[current],
            key=lambda edge: _edge_priority(edge, current, destination_floor),
        )
        for edge in ordered_edges:
            neighbor = edge.other(current)
            candidate = distance + edge.weight
            if candidate >= distances.get(neighbor, 10**9):
                continue
            distances[neighbor] = candidate
            previous[neighbor] = (current, edge.id)
            heapq.heappush(queue, (candidate, sequence, neighbor))
            sequence += 1

    if destination_node not in previous:
        raise ValueError("Campus map nodes are not connected")

    reversed_nodes = [destination_node]
    reversed_edges: list[str] = []
    current = destination_node
    while current != origin_node:
        prior, edge_id = previous[current]
        reversed_edges.append(edge_id)
        reversed_nodes.append(prior)
        current = prior
    return CampusRoute(
        nodes=tuple(reversed(reversed_nodes)),
        edges=tuple(reversed(reversed_edges)),
    )


def _edge_priority(
    edge: CampusEdge,
    current_node: str,
    destination_floor: int | None,
) -> tuple[int, int, int]:
    edge_index = next(index for index, candidate in enumerate(EDGES) if candidate.id == edge.id)
    if edge.kind != "connector" or edge.floor is None:
        return (2, 0, edge_index)
    if destination_floor is not None and edge.floor == destination_floor:
        return (0, 0, edge_index)
    current_floor = NODES[current_node].ground_floor
    floor_delta = abs(edge.floor - current_floor) if current_floor is not None else 10**3
    return (1, floor_delta, edge_index)


def generate_route_steps(
    route: CampusRoute,
    origin: ResolvedLocation,
    destination: ResolvedLocation,
) -> list[str]:
    if not route.nodes or route.nodes[0] != origin.node or route.nodes[-1] != destination.node:
        raise ValueError("Route endpoints do not match resolved locations")

    origin_name = origin.label
    if origin.floor is not None and origin.label == "図書館":
        origin_name = f"{origin.label}（{origin.floor}階）"
    steps = [f"{origin_name}を出る"]
    current_floor = origin.floor if origin.floor is not None else NODES[origin.node].ground_floor

    for index, edge_id in enumerate(route.edges):
        edge = EDGE_BY_ID[edge_id]
        next_node = NODES[route.nodes[index + 1]]

        if edge.kind == "connector":
            if current_floor != edge.floor:
                steps.append(f"エレベーターまたは階段で {edge.floor}階へ")
            steps.append(f"{edge.floor}階の連絡通路で {next_node.label}へ")
            current_floor = edge.floor
            continue

        if edge.kind == "indoor":
            if current_floor != edge.floor:
                steps.append(f"エレベーターまたは階段で {edge.floor}階へ")
            steps.append(f"{edge.floor}階の屋内接続で {next_node.label}へ")
            current_floor = edge.floor
        else:
            minutes = f"（徒歩 約{edge.minutes}分）" if edge.minutes is not None else ""
            steps.append(f"{next_node.label}方面へ{minutes}")
            current_floor = None

        if next_node.ground_floor is not None and next_node.ground_floor != 1:
            steps.append(
                f"{next_node.label}は {next_node.ground_floor}階が地上・"
                f"{next_node.ground_floor}階から入る"
            )
            current_floor = next_node.ground_floor
        elif current_floor is None:
            current_floor = next_node.ground_floor

    if destination.room:
        if destination.floor is not None:
            if current_floor != destination.floor:
                steps.append(
                    f"エレベーターまたは階段で {destination.floor}階へ → {destination.room}"
                )
            else:
                steps.append(f"{destination.room}（{destination.floor}階）へ")
        else:
            steps.append(
                f"{destination.room} の階は館内表示・当日スタッフでご確認ください"
            )
    else:
        steps.append(f"{destination.label}に到着")
    return steps


def route_map_payload(
    origin: ResolvedLocation,
    destination: ResolvedLocation,
) -> dict[str, Any]:
    route = find_shortest_route(
        origin.node,
        destination.node,
        destination_floor=destination.floor,
    )
    return {
        "mode": "route",
        "origin": origin.as_origin_payload(),
        "destination": destination.as_payload(),
        "path": {"nodes": list(route.nodes), "edges": list(route.edges)},
        "steps": generate_route_steps(route, origin, destination),
    }


def place_map_payload(destination: ResolvedLocation) -> dict[str, Any]:
    return {
        "mode": "place",
        "origin": None,
        "destination": destination.as_payload(),
    }


def ask_origin_map_payload(
    destination: ResolvedLocation,
    question: str,
) -> dict[str, Any]:
    return {
        "mode": "ask_origin",
        "origin": None,
        "destination": destination.as_payload(),
        "prompt": "いまいる場所をマップでタップしてください",
        "question": question,
    }


shortest_route = find_shortest_route
build_route_map_payload = route_map_payload
build_place_map_payload = place_map_payload
build_ask_origin_map_payload = ask_origin_map_payload
