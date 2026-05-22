from __future__ import annotations

import math
from array import array
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from OCP.BRep import BRep_Tool
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS


ColorRGBA = tuple[float, float, float, float]
CAD_TO_GLB_SCALE = 0.001
DEFAULT_MATERIAL: ColorRGBA = (0.72, 0.72, 0.72, 1.0)


@dataclass
class ShapeGlbMeshPayload:
    positions: array
    normals: array
    primitives: list[tuple[ColorRGBA, array]]
    minimum: list[float]
    maximum: list[float]
    face_runs_by_hash: dict[int, tuple[int, int, int]]


def normalize_rgba(color: ColorRGBA | tuple[float, ...] | None) -> ColorRGBA:
    if color is None:
        return DEFAULT_MATERIAL
    values = tuple(max(0.0, min(1.0, float(component))) for component in color)
    if len(values) == 3:
        return (values[0], values[1], values[2], 1.0)
    if len(values) >= 4:
        return (values[0], values[1], values[2], values[3])
    return DEFAULT_MATERIAL


def color_key(color: ColorRGBA) -> tuple[int, int, int, int]:
    return tuple(int(round(max(0.0, min(1.0, component)) * 255.0)) for component in color)


def occurrence_color_for_id(
    occurrence_id: str,
    occurrence_colors: Mapping[str, ColorRGBA],
) -> ColorRGBA | None:
    current = occurrence_id
    while current:
        color = occurrence_colors.get(current)
        if color is not None:
            return normalize_rgba(color)
        if "." not in current:
            break
        current = current.rsplit(".", 1)[0]
    return None


def _empty_payload() -> ShapeGlbMeshPayload:
    return ShapeGlbMeshPayload(
        positions=array("f"),
        normals=array("f"),
        primitives=[],
        minimum=[0.0, 0.0, 0.0],
        maximum=[0.0, 0.0, 0.0],
        face_runs_by_hash={},
    )


def _triangle_area_twice(
    a: Sequence[float],
    b: Sequence[float],
    c: Sequence[float],
) -> float:
    abx = b[0] - a[0]
    aby = b[1] - a[1]
    abz = b[2] - a[2]
    acx = c[0] - a[0]
    acy = c[1] - a[1]
    acz = c[2] - a[2]
    cross_x = aby * acz - abz * acy
    cross_y = abz * acx - abx * acz
    cross_z = abx * acy - aby * acx
    return math.sqrt(cross_x * cross_x + cross_y * cross_y + cross_z * cross_z)


def _transform_point_from_occ(point: object, location: TopLoc_Location) -> list[float]:
    transformed = point.Transformed(location.Transformation())
    return [float(transformed.X()), float(transformed.Y()), float(transformed.Z())]


def transform_normal_from_occ(
    normal: object,
    location: TopLoc_Location,
    *,
    reversed_face: bool,
) -> tuple[float, float, float]:
    transformed = normal.Transformed(location.Transformation())
    x = float(transformed.X())
    y = float(transformed.Y())
    z = float(transformed.Z())
    if reversed_face:
        x, y, z = -x, -y, -z
    length = math.sqrt((x * x) + (y * y) + (z * z))
    if length <= 1e-15 or not math.isfinite(length):
        return (0.0, 0.0, 1.0)
    return (x / length, y / length, z / length)


def _append_face_payload(
    *,
    positions: array,
    normals: array,
    primitive_indices_by_key: dict[tuple[int, int, int, int], tuple[int, ColorRGBA, array]],
    face_runs_by_hash: dict[int, tuple[int, int, int]],
    min_values: list[float],
    max_values: list[float],
    face_hash: int,
    default_color: ColorRGBA,
    face_colors: Mapping[int, ColorRGBA],
    nodes: Sequence[Sequence[float]],
    node_normals: Sequence[Sequence[float]],
    triangles: Sequence[Sequence[int]],
) -> None:
    if not nodes or not triangles:
        return

    normalized_color = normalize_rgba(face_colors.get(face_hash, default_color))
    key = color_key(normalized_color)
    bucket = primitive_indices_by_key.get(key)
    if bucket is None:
        bucket = (len(primitive_indices_by_key), normalized_color, array("I"))
        primitive_indices_by_key[key] = bucket
    primitive_index, _primitive_color, primitive_indices = bucket

    vertex_offset = len(positions) // 3
    for point in nodes:
        x = float(point[0]) * CAD_TO_GLB_SCALE
        y = float(point[1]) * CAD_TO_GLB_SCALE
        z = float(point[2]) * CAD_TO_GLB_SCALE
        positions.extend((x, y, z))
        min_values[0] = min(min_values[0], x)
        min_values[1] = min(min_values[1], y)
        min_values[2] = min(min_values[2], z)
        max_values[0] = max(max_values[0], x)
        max_values[1] = max(max_values[1], y)
        max_values[2] = max(max_values[2], z)

    fallback_normal = (0.0, 0.0, 1.0)
    if len(node_normals) != len(nodes):
        node_normals = [fallback_normal] * len(nodes)
    for normal in node_normals:
        normals.extend((float(normal[0]), float(normal[1]), float(normal[2])))

    triangle_start = len(primitive_indices) // 3
    for triangle in triangles:
        primitive_indices.extend(vertex_offset + int(node_index) for node_index in triangle)
    face_runs_by_hash[face_hash] = (primitive_index, triangle_start, len(triangles))


def prototype_glb_mesh_payload(
    prototype: Mapping[str, Any],
    *,
    default_color: ColorRGBA,
    face_colors: Mapping[int, ColorRGBA],
) -> ShapeGlbMeshPayload:
    positions = array("f")
    normals = array("f")
    primitive_indices_by_key: dict[tuple[int, int, int, int], tuple[int, ColorRGBA, array]] = {}
    face_runs_by_hash: dict[int, tuple[int, int, int]] = {}
    min_values = [math.inf, math.inf, math.inf]
    max_values = [-math.inf, -math.inf, -math.inf]

    for face_entry in prototype.get("faces", []):
        if not isinstance(face_entry, Mapping):
            continue
        face_hash = int(face_entry.get("shapeHash") or 0)
        triangles = face_entry.get("triangles", ())
        nodes = face_entry.get("triangleNodes", ())
        node_normals = face_entry.get("triangleNormals", ())
        if not node_normals:
            normal = face_entry.get("normal") or (0.0, 0.0, 1.0)
            node_normals = [normal] * len(nodes)
        _append_face_payload(
            positions=positions,
            normals=normals,
            primitive_indices_by_key=primitive_indices_by_key,
            face_runs_by_hash=face_runs_by_hash,
            min_values=min_values,
            max_values=max_values,
            face_hash=face_hash,
            default_color=default_color,
            face_colors=face_colors,
            nodes=nodes,
            node_normals=node_normals,
            triangles=triangles,
        )

    if not positions or not all(math.isfinite(value) for value in min_values + max_values):
        return _empty_payload()
    primitives = [
        (primitive_color, primitive_indices)
        for _index, primitive_color, primitive_indices in sorted(
            primitive_indices_by_key.values(),
            key=lambda item: item[0],
        )
    ]
    return ShapeGlbMeshPayload(
        positions=positions,
        normals=normals,
        primitives=primitives,
        minimum=min_values,
        maximum=max_values,
        face_runs_by_hash=face_runs_by_hash,
    )


def shape_glb_mesh_payload(
    shape: object,
    *,
    default_color: ColorRGBA,
    face_colors: Mapping[int, ColorRGBA],
) -> ShapeGlbMeshPayload:
    face_entries: list[dict[str, Any]] = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is None:
            explorer.Next()
            continue
        if not triangulation.HasNormals():
            triangulation.ComputeNormals()
        reversed_face = face.Orientation() == TopAbs_REVERSED
        nodes = [
            _transform_point_from_occ(triangulation.Node(index), location)
            for index in range(1, triangulation.NbNodes() + 1)
        ]
        node_normals = [
            transform_normal_from_occ(triangulation.Normal(index), location, reversed_face=reversed_face)
            for index in range(1, triangulation.NbNodes() + 1)
        ]
        triangles: list[tuple[int, int, int]] = []
        for index in range(1, triangulation.NbTriangles() + 1):
            node_a, node_b, node_c = triangulation.Triangle(index).Get()
            triangle = [node_a - 1, node_b - 1, node_c - 1]
            if reversed_face:
                triangle[1], triangle[2] = triangle[2], triangle[1]
            vertices = [nodes[node_index] for node_index in triangle]
            if _triangle_area_twice(vertices[0], vertices[1], vertices[2]) <= 1e-9:
                continue
            triangles.append((triangle[0], triangle[1], triangle[2]))
        if triangles:
            face_entries.append(
                {
                    "shapeHash": hash(face),
                    "triangleNodes": nodes,
                    "triangleNormals": node_normals,
                    "triangles": triangles,
                }
            )
        explorer.Next()
    return prototype_glb_mesh_payload(
        {"faces": face_entries},
        default_color=default_color,
        face_colors=face_colors,
    )


def scene_glb_mesh_payload_key(
    scene: object,
    prototype_key: int,
    *,
    default_color: ColorRGBA,
    suppress_face_colors: bool,
) -> tuple[object, ...]:
    return (
        int(prototype_key),
        color_key(normalize_rgba(default_color)),
        bool(suppress_face_colors),
        getattr(scene, "mesh_signature", None),
    )


def scene_glb_mesh_payload(
    scene: object,
    prototype_key: int,
    *,
    default_color: ColorRGBA,
    suppress_face_colors: bool,
    prototype: Mapping[str, Any] | None = None,
) -> ShapeGlbMeshPayload:
    key = scene_glb_mesh_payload_key(
        scene,
        prototype_key,
        default_color=default_color,
        suppress_face_colors=suppress_face_colors,
    )
    cache = getattr(scene, "glb_mesh_payloads", None)
    if cache is None:
        cache = {}
        setattr(scene, "glb_mesh_payloads", cache)
    cached = cache.get(key)
    if cached is not None:
        return cached

    face_colors = (
        {}
        if suppress_face_colors
        else getattr(scene, "prototype_face_colors", {}).get(prototype_key, {})
    )
    if prototype is not None:
        payload = prototype_glb_mesh_payload(
            prototype,
            default_color=normalize_rgba(default_color),
            face_colors=face_colors,
        )
    else:
        shape = getattr(scene, "prototype_shapes", {}).get(prototype_key)
        payload = (
            _empty_payload()
            if shape is None
            else shape_glb_mesh_payload(
                shape,
                default_color=normalize_rgba(default_color),
                face_colors=face_colors,
            )
        )
    cache[key] = payload
    return payload
