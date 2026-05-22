from __future__ import annotations

import json
import os
import struct
from array import array
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from common.selector_types import SelectorBundle


STEP_TOPOLOGY_EXTENSION = "STEP_topology"
STEP_TOPOLOGY_SCHEMA_VERSION = 1
GLB_MAGIC = 0x46546C67
GLB_VERSION = 2
REPO_ROOT = Path.cwd().resolve()


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _parse_glb_header(path: Path, payload: bytes) -> tuple[int, int]:
    if len(payload) < 20:
        raise ValueError(f"Not a GLB file: {_display_path(path)}")
    magic, version, length = struct.unpack_from("<III", payload, 0)
    if magic != GLB_MAGIC or version != GLB_VERSION or length > len(payload):
        raise ValueError(f"Not a GLB v2 file: {_display_path(path)}")
    return version, length


def _read_glb_chunks(path: Path) -> tuple[dict[str, Any], bytes]:
    payload = path.expanduser().resolve().read_bytes()
    _, length = _parse_glb_header(path, payload)
    offset = 12
    json_payload: bytes | None = None
    binary_payload = b""
    while offset + 8 <= length:
        chunk_length, chunk_type = struct.unpack_from("<I4s", payload, offset)
        offset += 8
        chunk = payload[offset : offset + chunk_length]
        offset += chunk_length
        if chunk_type == b"JSON":
            json_payload = chunk
        elif chunk_type == b"BIN\0":
            binary_payload = chunk
    if json_payload is None:
        raise ValueError(f"GLB is missing JSON chunk: {_display_path(path)}")
    gltf = json.loads(json_payload.decode("utf-8").rstrip(" \t\r\n\0"))
    if not isinstance(gltf, dict):
        raise ValueError(f"GLB JSON chunk is not an object: {_display_path(path)}")
    return gltf, binary_payload


def _read_glb_json_and_bin_location(path: Path) -> tuple[dict[str, Any], int, int]:
    resolved = path.expanduser().resolve()
    with resolved.open("rb") as handle:
        header = handle.read(12)
        if len(header) != 12:
            raise ValueError(f"Not a GLB file: {_display_path(path)}")
        magic, version, length = struct.unpack("<III", header)
        if magic != GLB_MAGIC or version != GLB_VERSION:
            raise ValueError(f"Not a GLB v2 file: {_display_path(path)}")
        file_size = resolved.stat().st_size
        if length > file_size:
            raise ValueError(f"Not a GLB v2 file: {_display_path(path)}")
        offset = 12
        json_payload: bytes | None = None
        binary_offset = 0
        binary_length = 0
        while offset + 8 <= length:
            handle.seek(offset)
            chunk_header = handle.read(8)
            if len(chunk_header) != 8:
                break
            chunk_length, chunk_type = struct.unpack("<I4s", chunk_header)
            offset += 8
            if offset + chunk_length > length:
                raise ValueError(f"Invalid GLB chunk length: {_display_path(path)}")
            if chunk_type == b"JSON":
                json_payload = handle.read(chunk_length)
            elif chunk_type == b"BIN\0":
                binary_offset = offset
                binary_length = chunk_length
                handle.seek(chunk_length, os.SEEK_CUR)
            else:
                handle.seek(chunk_length, os.SEEK_CUR)
            offset += chunk_length
    if json_payload is None:
        raise ValueError(f"GLB is missing JSON chunk: {_display_path(path)}")
    gltf = json.loads(json_payload.decode("utf-8").rstrip(" \t\r\n\0"))
    if not isinstance(gltf, dict):
        raise ValueError(f"GLB JSON chunk is not an object: {_display_path(path)}")
    return gltf, binary_offset, binary_length


def _buffer_view_range(gltf: Mapping[str, Any], binary_offset: int, binary_length: int, view_index: object) -> tuple[int, int]:
    if not isinstance(view_index, int):
        raise ValueError("GLB bufferView index must be an integer")
    buffer_views = gltf.get("bufferViews")
    if not isinstance(buffer_views, list) or not (0 <= view_index < len(buffer_views)):
        raise ValueError(f"GLB bufferView index is out of range: {view_index}")
    view = buffer_views[view_index]
    if not isinstance(view, Mapping):
        raise ValueError(f"GLB bufferView is not an object: {view_index}")
    if int(view.get("buffer") or 0) != 0:
        raise ValueError("STEP topology only supports GLB buffer 0")
    byte_offset = int(view.get("byteOffset") or 0)
    byte_length = int(view.get("byteLength") or 0)
    if byte_offset < 0 or byte_length < 0 or byte_offset + byte_length > binary_length:
        raise ValueError(f"GLB bufferView range is invalid: {view_index}")
    return binary_offset + byte_offset, byte_length


def _read_file_range(path: Path, byte_offset: int, byte_length: int) -> bytes:
    with path.expanduser().resolve().open("rb") as handle:
        handle.seek(byte_offset)
        payload = handle.read(byte_length)
    if len(payload) != byte_length:
        raise ValueError("GLB bufferView range is invalid")
    return payload


def _buffer_view_bytes(gltf: Mapping[str, Any], binary_payload: bytes, view_index: object) -> bytes:
    byte_offset, byte_length = _buffer_view_range(gltf, 0, len(binary_payload), view_index)
    return binary_payload[byte_offset : byte_offset + byte_length]


def _array_from_view(gltf: Mapping[str, Any], binary_payload: bytes, view: Mapping[str, Any]) -> array:
    dtype = str(view.get("dtype") or "")
    typecode = "f" if dtype == "float32" else "I" if dtype == "uint32" else ""
    if not typecode:
        raise ValueError(f"Unsupported STEP topology buffer dtype: {dtype}")
    raw = _buffer_view_bytes(gltf, binary_payload, view.get("bufferView"))
    byte_offset = int(view.get("byteOffset") or 0)
    count = int(view.get("count") or 0)
    item_size = int(view.get("itemSize") or array(typecode).itemsize)
    byte_length = int(view.get("byteLength") or (count * item_size))
    if byte_offset < 0 or byte_length < 0 or byte_offset + byte_length > len(raw):
        raise ValueError("STEP topology buffer view range is invalid")
    values = array(typecode)
    values.frombytes(raw[byte_offset : byte_offset + byte_length])
    if count >= 0 and len(values) > count:
        del values[count:]
    return values


def _array_from_legacy_binary_view(binary_payload: bytes, view: Mapping[str, Any]) -> array:
    dtype = str(view.get("dtype") or "")
    typecode = "f" if dtype == "float32" else "I" if dtype == "uint32" else ""
    if not typecode:
        raise ValueError(f"Unsupported STEP topology buffer dtype: {dtype}")
    byte_offset = int(view.get("byteOffset") or 0)
    count = int(view.get("count") or 0)
    item_size = int(view.get("itemSize") or array(typecode).itemsize)
    byte_length = int(view.get("byteLength") or (count * item_size))
    if byte_offset < 0 or byte_length < 0 or byte_offset + byte_length > len(binary_payload):
        raise ValueError("STEP topology buffer view range is invalid")
    values = array(typecode)
    values.frombytes(binary_payload[byte_offset : byte_offset + byte_length])
    if count >= 0 and len(values) > count:
        del values[count:]
    return values


def _step_topology_extension(gltf: Mapping[str, Any]) -> Mapping[str, Any] | None:
    extensions = gltf.get("extensions")
    extension = extensions.get(STEP_TOPOLOGY_EXTENSION) if isinstance(extensions, Mapping) else None
    if not isinstance(extension, Mapping):
        return None
    if int(extension.get("schemaVersion") or 0) != STEP_TOPOLOGY_SCHEMA_VERSION:
        return None
    if str(extension.get("encoding") or "utf-8").lower() != "utf-8":
        return None
    return extension


def _legacy_topology_manifest_path_for_glb(glb_path: Path) -> Path | None:
    resolved = glb_path.expanduser().resolve()
    if resolved.name != "model.glb":
        return None
    return resolved.parent / "topology.json"


def _read_legacy_topology_manifest(glb_path: Path) -> dict[str, Any] | None:
    manifest_path = _legacy_topology_manifest_path_for_glb(glb_path)
    if manifest_path is None or not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return manifest if isinstance(manifest, dict) else None


def _read_legacy_topology_bundle(glb_path: Path) -> SelectorBundle | None:
    manifest = _read_legacy_topology_manifest(glb_path)
    if manifest is None:
        return None
    buffers: dict[str, array] = {}
    buffer_spec = manifest.get("buffers")
    views = buffer_spec.get("views") if isinstance(buffer_spec, Mapping) else None
    uri = str(buffer_spec.get("uri") or "") if isinstance(buffer_spec, Mapping) else ""
    if isinstance(views, Mapping) and uri:
        manifest_path = _legacy_topology_manifest_path_for_glb(glb_path)
        bin_path = manifest_path.parent / uri if manifest_path is not None else Path(uri)
        try:
            binary_payload = bin_path.read_bytes()
        except OSError:
            binary_payload = b""
        if binary_payload:
            for name, view in views.items():
                if not isinstance(view, Mapping):
                    continue
                try:
                    buffers[str(name)] = _array_from_legacy_binary_view(binary_payload, view)
                except ValueError:
                    continue
    return SelectorBundle(manifest=manifest, buffers=buffers)


def read_step_topology_bundle_from_glb(glb_path: Path) -> SelectorBundle | None:
    try:
        gltf, binary_payload = _read_glb_chunks(glb_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return _read_legacy_topology_bundle(glb_path)
    extension = _step_topology_extension(gltf)
    if extension is None:
        return _read_legacy_topology_bundle(glb_path)
    try:
        manifest_bytes = _buffer_view_bytes(gltf, binary_payload, extension.get("selectorView"))
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return _read_legacy_topology_bundle(glb_path)
    if not isinstance(manifest, dict):
        return None
    buffers: dict[str, array] = {}
    views = manifest.get("buffers", {}).get("views") if isinstance(manifest.get("buffers"), Mapping) else None
    if isinstance(views, Mapping):
        for name, view in views.items():
            if not isinstance(view, Mapping):
                continue
            try:
                buffers[str(name)] = _array_from_view(gltf, binary_payload, view)
            except ValueError:
                continue
    return SelectorBundle(manifest=manifest, buffers=buffers)


def read_step_topology_index_from_glb(glb_path: Path) -> dict[str, Any] | None:
    try:
        gltf, binary_offset, binary_length = _read_glb_json_and_bin_location(glb_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return _read_legacy_topology_manifest(glb_path)
    extension = _step_topology_extension(gltf)
    if extension is None:
        return _read_legacy_topology_manifest(glb_path)
    try:
        manifest_offset, manifest_length = _buffer_view_range(
            gltf,
            binary_offset,
            binary_length,
            extension.get("indexView"),
        )
        manifest = json.loads(_read_file_range(glb_path, manifest_offset, manifest_length).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, OSError):
        return None
    return manifest if isinstance(manifest, dict) else None


def read_step_topology_manifest_from_glb(glb_path: Path) -> dict[str, Any] | None:
    return read_step_topology_index_from_glb(glb_path)
