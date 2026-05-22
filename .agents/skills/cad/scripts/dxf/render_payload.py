from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import ezdxf


DXF_RENDER_SCHEMA_VERSION = 1
SUPPORTED_ENTITY_TYPES = {"LINE", "ARC", "CIRCLE", "LWPOLYLINE"}
ANGLE_EPSILON = 1e-9


@dataclass(frozen=True)
class LineEntity:
    layer: str
    start: tuple[float, float]
    end: tuple[float, float]


@dataclass(frozen=True)
class ArcEntity:
    layer: str
    center: tuple[float, float]
    radius: float
    start_angle_deg: float
    sweep_angle_deg: float

    @property
    def end_angle_deg(self) -> float:
        return self.start_angle_deg + self.sweep_angle_deg


@dataclass(frozen=True)
class CircleEntity:
    layer: str
    center: tuple[float, float]
    radius: float


def _normalize_layer_name(value: object) -> str:
    text = str(value or "").strip()
    return text or "0"


def _semantic_kind_for_layer(layer_name: str) -> str:
    return "bend" if "bend" in layer_name.strip().lower() else "cut"


def _normalize_angle(angle_deg: float) -> float:
    value = math.fmod(angle_deg, 360.0)
    return value + 360.0 if value < 0.0 else value


def _angle_in_ccw_sweep(angle_deg: float, start_angle_deg: float, sweep_angle_deg: float) -> bool:
    if sweep_angle_deg >= 360.0 - ANGLE_EPSILON:
        return True
    normalized_delta = (_normalize_angle(angle_deg) - _normalize_angle(start_angle_deg)) % 360.0
    return normalized_delta <= sweep_angle_deg + ANGLE_EPSILON


def _point_on_circle(center: tuple[float, float], radius: float, angle_deg: float) -> tuple[float, float]:
    radians = math.radians(angle_deg)
    return (
        center[0] + radius * math.cos(radians),
        center[1] + radius * math.sin(radians),
    )


def _arc_extrema_points(arc: ArcEntity) -> list[tuple[float, float]]:
    points = [
        _point_on_circle(arc.center, arc.radius, arc.start_angle_deg),
        _point_on_circle(arc.center, arc.radius, arc.end_angle_deg),
    ]
    for candidate_angle in (0.0, 90.0, 180.0, 270.0):
        if _angle_in_ccw_sweep(candidate_angle, arc.start_angle_deg, arc.sweep_angle_deg):
            points.append(_point_on_circle(arc.center, arc.radius, candidate_angle))
    return points


def _line_bounds(line: LineEntity) -> tuple[float, float, float, float]:
    xs = (line.start[0], line.end[0])
    ys = (line.start[1], line.end[1])
    return (min(xs), min(ys), max(xs), max(ys))


def _circle_bounds(circle: CircleEntity) -> tuple[float, float, float, float]:
    cx, cy = circle.center
    r = circle.radius
    return (cx - r, cy - r, cx + r, cy + r)


def _arc_bounds(arc: ArcEntity) -> tuple[float, float, float, float]:
    points = _arc_extrema_points(arc)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _expand_bounds(
    current: tuple[float, float, float, float] | None,
    next_bounds: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    if current is None:
        return next_bounds
    return (
        min(current[0], next_bounds[0]),
        min(current[1], next_bounds[1]),
        max(current[2], next_bounds[2]),
        max(current[3], next_bounds[3]),
    )


def _screen_point(point: tuple[float, float], *, min_x: float, max_y: float) -> tuple[float, float]:
    return (point[0] - min_x, max_y - point[1])


def _format_number(value: float) -> float:
    rounded = round(float(value), 6)
    return 0.0 if abs(rounded) < ANGLE_EPSILON else rounded


def _build_path_record(layer_name: str, semantic_kind: str, path_data: str) -> dict[str, object]:
    return {"layer": layer_name, "kind": semantic_kind, "d": path_data}


def _lwpolyline_lines(entity, *, layer_name: str, dxf_path: Path) -> list[LineEntity]:
    vertices: list[tuple[float, float]] = []
    for point in entity:
        bulge = float(point[4]) if len(point) > 4 else 0.0
        if abs(bulge) > ANGLE_EPSILON:
            raise ValueError(
                f"Unsupported DXF LWPOLYLINE bulge in {dxf_path.as_posix()}; "
                "only straight-segment LWPOLYLINE entities are supported"
            )
        vertices.append((float(point[0]), float(point[1])))

    if len(vertices) < 2:
        raise ValueError(f"Invalid DXF LWPOLYLINE in {dxf_path.as_posix()}: expected at least 2 vertices")

    lines: list[LineEntity] = []
    for start, end in zip(vertices, vertices[1:]):
        if start == end:
            continue
        lines.append(LineEntity(layer=layer_name, start=start, end=end))
    if entity.closed and vertices[0] != vertices[-1]:
        lines.append(LineEntity(layer=layer_name, start=vertices[-1], end=vertices[0]))
    return lines


def _load_dxf_entities(document, dxf_path: Path) -> tuple[list[LineEntity], list[ArcEntity], list[CircleEntity]]:
    modelspace = document.modelspace()
    lines: list[LineEntity] = []
    arcs: list[ArcEntity] = []
    circles: list[CircleEntity] = []

    for entity in modelspace:
        entity_type = entity.dxftype()
        if entity_type not in SUPPORTED_ENTITY_TYPES:
            raise ValueError(
                f"Unsupported DXF entity {entity_type} in {dxf_path.as_posix()}; "
                f"supported types: {', '.join(sorted(SUPPORTED_ENTITY_TYPES))}"
            )

        layer_name = _normalize_layer_name(entity.dxf.layer)
        if entity_type == "LINE":
            lines.append(
                LineEntity(
                    layer=layer_name,
                    start=(float(entity.dxf.start.x), float(entity.dxf.start.y)),
                    end=(float(entity.dxf.end.x), float(entity.dxf.end.y)),
                )
            )
            continue

        if entity_type == "LWPOLYLINE":
            lines.extend(_lwpolyline_lines(entity, layer_name=layer_name, dxf_path=dxf_path))
            continue

        if entity_type == "ARC":
            radius = float(entity.dxf.radius)
            if radius <= 0.0:
                raise ValueError(f"Invalid DXF arc radius in {dxf_path.as_posix()}: {radius}")
            start_angle_deg = _normalize_angle(float(entity.dxf.start_angle))
            end_angle_deg = _normalize_angle(float(entity.dxf.end_angle))
            sweep_angle_deg = (end_angle_deg - start_angle_deg) % 360.0
            if sweep_angle_deg <= ANGLE_EPSILON:
                sweep_angle_deg = 360.0
            arcs.append(
                ArcEntity(
                    layer=layer_name,
                    center=(float(entity.dxf.center.x), float(entity.dxf.center.y)),
                    radius=radius,
                    start_angle_deg=start_angle_deg,
                    sweep_angle_deg=sweep_angle_deg,
                )
            )
            continue

        radius = float(entity.dxf.radius)
        if radius <= 0.0:
            raise ValueError(f"Invalid DXF circle radius in {dxf_path.as_posix()}: {radius}")
        circles.append(
            CircleEntity(
                layer=layer_name,
                center=(float(entity.dxf.center.x), float(entity.dxf.center.y)),
                radius=radius,
            )
        )

    if not lines and not arcs and not circles:
        raise ValueError(f"No supported DXF entities found in {dxf_path.as_posix()}")

    return lines, arcs, circles


def build_dxf_render_payload(dxf_path: Path, *, file_ref: str) -> dict[str, object]:
    source_path = dxf_path.resolve()
    document = ezdxf.readfile(source_path)
    lines, arcs, circles = _load_dxf_entities(document, source_path)

    raw_bounds: tuple[float, float, float, float] | None = None
    for line in lines:
        raw_bounds = _expand_bounds(raw_bounds, _line_bounds(line))
    for arc in arcs:
        raw_bounds = _expand_bounds(raw_bounds, _arc_bounds(arc))
    for circle in circles:
        raw_bounds = _expand_bounds(raw_bounds, _circle_bounds(circle))

    if raw_bounds is None:
        raise ValueError(f"Failed to compute DXF bounds for {source_path.as_posix()}")

    min_x, min_y, max_x, max_y = raw_bounds
    width = max(max_x - min_x, 0.0)
    height = max(max_y - min_y, 0.0)

    path_records: list[dict[str, object]] = []
    circle_records: list[dict[str, object]] = []
    layer_summary: dict[str, dict[str, object]] = {}

    def touch_layer(layer_name: str) -> dict[str, object]:
        summary = layer_summary.get(layer_name)
        if summary is not None:
            return summary
        summary = {
            "name": layer_name,
            "kind": _semantic_kind_for_layer(layer_name),
            "pathCount": 0,
            "circleCount": 0,
        }
        layer_summary[layer_name] = summary
        return summary

    for line in lines:
        start = _screen_point(line.start, min_x=min_x, max_y=max_y)
        end = _screen_point(line.end, min_x=min_x, max_y=max_y)
        path_records.append(
            _build_path_record(
                line.layer,
                _semantic_kind_for_layer(line.layer),
                (
                    f"M {_format_number(start[0])} {_format_number(start[1])} "
                    f"L {_format_number(end[0])} {_format_number(end[1])}"
                ),
            )
        )
        touch_layer(line.layer)["pathCount"] += 1

    for arc in arcs:
        start_point = _screen_point(
            _point_on_circle(arc.center, arc.radius, arc.start_angle_deg),
            min_x=min_x,
            max_y=max_y,
        )
        end_point = _screen_point(
            _point_on_circle(arc.center, arc.radius, arc.end_angle_deg),
            min_x=min_x,
            max_y=max_y,
        )
        large_arc_flag = 1 if arc.sweep_angle_deg > 180.0 + ANGLE_EPSILON else 0
        path_records.append(
            _build_path_record(
                arc.layer,
                _semantic_kind_for_layer(arc.layer),
                (
                    f"M {_format_number(start_point[0])} {_format_number(start_point[1])} "
                    f"A {_format_number(arc.radius)} {_format_number(arc.radius)} 0 "
                    f"{large_arc_flag} 1 {_format_number(end_point[0])} {_format_number(end_point[1])}"
                ),
            )
        )
        touch_layer(arc.layer)["pathCount"] += 1

    for circle in circles:
        center = _screen_point(circle.center, min_x=min_x, max_y=max_y)
        circle_records.append(
            {
                "layer": circle.layer,
                "kind": _semantic_kind_for_layer(circle.layer),
                "cx": _format_number(center[0]),
                "cy": _format_number(center[1]),
                "r": _format_number(circle.radius),
            }
        )
        touch_layer(circle.layer)["circleCount"] += 1

    return {
        "schemaVersion": DXF_RENDER_SCHEMA_VERSION,
        "fileRef": file_ref,
        "sourceUnits": int(getattr(document, "units", 0) or 0),
        "defaultThicknessMm": 0.0,
        "bounds": {
            "minX": 0.0,
            "minY": 0.0,
            "maxX": _format_number(width),
            "maxY": _format_number(height),
            "width": _format_number(width),
            "height": _format_number(height),
        },
        "counts": {
            "paths": len(path_records),
            "circles": len(circle_records),
            "entities": len(path_records) + len(circle_records),
        },
        "layers": [layer_summary[name] for name in sorted(layer_summary)],
        "geometry": {
            "lines": [
                {
                    "layer": line.layer,
                    "kind": _semantic_kind_for_layer(line.layer),
                    "start": [_format_number(line.start[0]), _format_number(line.start[1])],
                    "end": [_format_number(line.end[0]), _format_number(line.end[1])],
                }
                for line in lines
            ],
            "arcs": [
                {
                    "layer": arc.layer,
                    "kind": _semantic_kind_for_layer(arc.layer),
                    "center": [_format_number(arc.center[0]), _format_number(arc.center[1])],
                    "radius": _format_number(arc.radius),
                    "startAngleDeg": _format_number(arc.start_angle_deg),
                    "sweepAngleDeg": _format_number(arc.sweep_angle_deg),
                }
                for arc in arcs
            ],
            "circles": [
                {
                    "layer": circle.layer,
                    "kind": _semantic_kind_for_layer(circle.layer),
                    "center": [_format_number(circle.center[0]), _format_number(circle.center[1])],
                    "radius": _format_number(circle.radius),
                }
                for circle in circles
            ],
        },
        "paths": path_records,
        "circles": circle_records,
    }
