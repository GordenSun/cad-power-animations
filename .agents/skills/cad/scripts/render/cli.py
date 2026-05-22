from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import math
import mimetypes
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import parse_qs, unquote, urlparse

import numpy as np

if __package__ in {None, ""}:
    package_dir = Path(__file__).resolve().parent
    scripts_dir = package_dir.parent
    sys.path = [
        entry
        for entry in sys.path
        if not entry or Path(entry).resolve() != package_dir
    ]
    sys.path.insert(0, str(scripts_dir))

from common.step_targets import (
    CadRefError,
    ResolvedStepTarget,
    resolve_step_target,
    validate_step_topology_artifact,
)
from common.cli_logging import CliLogger
from common.glb_topology import read_step_topology_bundle_from_glb, read_step_topology_manifest_from_glb

REPO_ROOT = Path.cwd().resolve()
CAD_ROOT = REPO_ROOT
DEFAULT_MODEL_COLOR = (0.80, 0.84, 0.90)
DEFAULT_BACKGROUND_COLOR = (0.98, 0.985, 0.99)
TECHNICAL_LINE_COLOR = (0x22 / 255.0, 0x44 / 255.0, 0x66 / 255.0)
WORLD_UP = (0.0, 0.0, 1.0)
TOP_VIEW_UP = (0.0, 1.0, 0.0)
FALLBACK_COMPONENT_COLORS: tuple[tuple[float, float, float], ...] = (
    (0.82, 0.84, 0.88),
    (0.68, 0.77, 0.91),
    (0.70, 0.86, 0.79),
    (0.93, 0.79, 0.62),
    (0.88, 0.72, 0.78),
    (0.76, 0.72, 0.90),
    (0.85, 0.83, 0.62),
    (0.68, 0.86, 0.87),
)
FEATURE_EDGE_ANGLE_DEG = 32.0
BASE_MARGIN_PX = 12.0
CROP_PADDING_PX = 12
AXIS_BOX_SIZE_PX = 46
GLB_TO_CAD_SCALE = 1000.0
EDGE_STYLES = ("off", "thin", "bold")
PRESETS = ("solid", "technical", "clay", "component", "xray", "normals", "depth", "silhouette")
COLOR_BY_MODES = ("step", "occurrence", "none")
QUALITY_LEVELS = ("draft", "low", "standard", "medium", "high", "very-high")
QUALITY_RENDER_SCALE = {
    "draft": 1.0,
    "low": 1.0,
    "standard": 1.5,
    "medium": 1.5,
    "high": 2.0,
    "very-high": 3.0,
}
ORBIT_QUALITY_PROFILES: dict[str, dict[str, float | int]] = {
    "draft": {"width": 360, "height": 240, "fps": 8.0, "duration_seconds": 2.0},
    "low": {"width": 480, "height": 320, "fps": 10.0, "duration_seconds": 2.4},
    "standard": {"width": 720, "height": 480, "fps": 12.0, "duration_seconds": 3.0},
    "medium": {"width": 960, "height": 640, "fps": 15.0, "duration_seconds": 3.2},
    "high": {"width": 1200, "height": 800, "fps": 18.0, "duration_seconds": 4.0},
    "very-high": {"width": 1600, "height": 1000, "fps": 24.0, "duration_seconds": 4.0},
}
ORBIT_MAX_FRAMES = 720
ORBIT_MAX_FPS = 60.0
ORBIT_MAX_DURATION_SECONDS = 60.0
BROWSER_RENDER_DIR = Path(__file__).resolve().parent / "browser"
BROWSER_RENDER_HTML = BROWSER_RENDER_DIR / "render.html"
BROWSER_RENDER_ENTRY = BROWSER_RENDER_DIR / "render_entry.js"
BROWSER_RENDER_THREE_ROOT = Path(__file__).resolve().parents[2] / "explorer" / "node_modules" / "three"
DEFAULT_BROWSER_RENDER_TIMEOUT_SECONDS = 300.0
RENDER_DAEMON_PROTOCOL_VERSION = 1
RENDER_DAEMON_IDLE_TIMEOUT_SECONDS = 600.0
RENDER_DAEMON_MAX_JOBS = 100
RENDER_DAEMON_START_TIMEOUT_SECONDS = 15.0
RENDER_DAEMON_CONNECT_TIMEOUT_SECONDS = 2.0
PLAYWRIGHT_INSTALL_HINT = (
    "Install Playwright Chromium with: ./.venv/bin/python -m playwright install chromium"
)
_STARTED_RENDER_DAEMON_PROCESSES: dict[str, subprocess.Popen[bytes]] = {}


@dataclass(frozen=True)
class CameraView:
    name: str
    direction: tuple[float, float, float]
    up: tuple[float, float, float]


@dataclass(frozen=True)
class OrbitSettings:
    width: int
    height: int
    fps: float
    frame_count: int
    duration_seconds: float
    frame_duration_ms: int
    start_azimuth: float
    elevation: float
    turns: float
    quality: str


VIEW_PRESETS: dict[str, CameraView] = {
    "front": CameraView(name="front", direction=(0.0, -1.0, 0.0), up=WORLD_UP),
    "back": CameraView(name="back", direction=(0.0, 1.0, 0.0), up=WORLD_UP),
    "right": CameraView(name="right", direction=(1.0, 0.0, 0.0), up=WORLD_UP),
    "left": CameraView(name="left", direction=(-1.0, 0.0, 0.0), up=WORLD_UP),
    "top": CameraView(name="top", direction=(0.0, 0.0, 1.0), up=TOP_VIEW_UP),
    "bottom": CameraView(name="bottom", direction=(0.0, 0.0, -1.0), up=TOP_VIEW_UP),
    "iso": CameraView(name="iso", direction=(1.0, -1.0, 0.8), up=WORLD_UP),
    "isometric": CameraView(name="iso", direction=(1.0, -1.0, 0.8), up=WORLD_UP),
    "side": CameraView(name="side", direction=(1.0, 0.0, 0.0), up=WORLD_UP),
}


@dataclass(frozen=True)
class MeshInstance:
    vertices: np.ndarray
    triangles: np.ndarray
    color_rgb: tuple[float, float, float] | None = None
    face_colors_rgb: np.ndarray | None = None
    part_id: str = ""
    name: str = ""
    source_name: str = ""
    source_path: str = ""


@dataclass(frozen=True)
class GlbRenderTarget:
    glb_path: Path
    source_path: Path | None
    display_path: str
    manifest: dict[str, Any]
    target_focus: str = ""


@dataclass(frozen=True)
class GlbScenePart:
    scene: Any
    node_name: str
    geometry_name: str
    transform: np.ndarray
    part_id: str
    occurrence_id: str
    name: str
    source_name: str
    source_path: str
    color_rgb: tuple[float, float, float] | None


@dataclass(frozen=True)
class ProjectedMeshInstance:
    screen_points: np.ndarray
    view_points: np.ndarray
    triangles: np.ndarray
    face_brightness: np.ndarray
    face_normals: np.ndarray
    feature_edges: tuple[tuple[int, int], ...]
    color_rgb: tuple[float, float, float]
    face_colors_rgb: np.ndarray | None


def _rgb_default(rgb: tuple[float, float, float]) -> str:
    return ",".join(str(channel) for channel in rgb)


def parse_rgb(raw_value: str) -> tuple[float, float, float]:
    value = raw_value.strip()
    if value.startswith("#") and len(value) in {4, 7}:
        if len(value) == 4:
            red, green, blue = (int(character * 2, 16) for character in value[1:])
        else:
            red = int(value[1:3], 16)
            green = int(value[3:5], 16)
            blue = int(value[5:7], 16)
        return (red / 255.0, green / 255.0, blue / 255.0)
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 3:
        raise ValueError(f"Invalid RGB value: {raw_value}")
    rgb = tuple(float(part) for part in parts)
    if not all(0.0 <= channel <= 1.0 for channel in rgb):
        raise ValueError(f"RGB values must be in range [0, 1]: {raw_value}")
    return rgb  # type: ignore[return-value]


def resolve_view(view: str | CameraView) -> CameraView:
    if not isinstance(view, str):
        return view
    value = view.strip().lower()
    if value in VIEW_PRESETS:
        return VIEW_PRESETS[value]
    parts = value.split(":")
    if len(parts) in {2, 3}:
        try:
            azimuth = math.radians(float(parts[0]))
            elevation = math.radians(float(parts[1]))
        except ValueError as exc:
            raise ValueError(f"Invalid camera: {view}") from exc
        direction = (
            math.cos(elevation) * math.cos(azimuth),
            math.cos(elevation) * math.sin(azimuth),
            math.sin(elevation),
        )
        return CameraView(name=value.replace(":", "_"), direction=direction, up=WORLD_UP)
    raise ValueError(f"Unknown camera {view!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="render",
        description="Render review images from package-local GLB artifacts with STEP_topology v1.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  render view STEP/part.step --camera iso -o /tmp/part.png\n"
            "  render view STEP/.part.step.glb --camera iso -o /tmp/part.png\n"
            "  render view '@cad[STEP/assembly#o1.2]' --camera top -o /tmp/focus.png\n"
            "  render list STEP/assembly.step --format text\n"
        ),
    )
    add_render_commands(parser, command_dest="command")
    return parser


def add_render_commands(parser: argparse.ArgumentParser, *, command_dest: str) -> None:
    subparsers = parser.add_subparsers(dest=command_dest, required=True)

    def add_step_input(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "input",
            help="model.glb path, STEP/STP locator, CAD path, or @cad[...] ref.",
        )

    def add_output_args(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--output", "--out", "-o", dest="output", type=Path, help="Output image or SVG path.")
        subparser.add_argument(
            "--out-dir",
            type=Path,
            help="Write one image per camera into this directory. Required when --camera is repeated.",
        )

    def add_logging_args(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--quiet", action="store_true", help="Reduce nonessential output.")
        subparser.add_argument(
            "--verbose",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Show detailed progress and timing information.",
        )

    def add_render_args(subparser: argparse.ArgumentParser) -> None:
        add_step_input(subparser)
        add_output_args(subparser)
        subparser.add_argument(
            "--camera",
            action="append",
            default=None,
            help="Camera preset or azimuth:elevation[:distance]. Can be repeated.",
        )
        subparser.add_argument("--width", type=int, default=1400, help="Maximum output width.")
        subparser.add_argument("--height", type=int, default=900, help="Maximum output height.")
        subparser.add_argument("--size", type=int, help="Set both width and height.")
        subparser.add_argument(
            "--background",
            default=_rgb_default(DEFAULT_BACKGROUND_COLOR),
            help="Background RGB as '#rrggbb' or 0..1 comma values.",
        )
        subparser.add_argument("--transparent", action="store_true", help="Make background pixels transparent.")
        subparser.add_argument("--focus", help="Comma-separated occurrence, name, source, or @cad selectors.")
        subparser.add_argument("--hide", help="Comma-separated occurrence, name, source, or @cad selectors.")
        subparser.add_argument("--preset", choices=PRESETS, default="solid")
        subparser.add_argument(
            "--quality",
            choices=QUALITY_LEVELS,
            default="high",
            help="PNG supersampling quality for browser renders; GLB tessellation is controlled at generation time.",
        )
        subparser.add_argument(
            "--color-by",
            choices=COLOR_BY_MODES,
            default=None,
            help="Color policy: STEP colors, occurrence debug colors, or one neutral color.",
        )
        subparser.add_argument("--edges", choices=EDGE_STYLES, default="thin")
        subparser.add_argument("--axes", action=argparse.BooleanOptionalAction, default=True)
        subparser.add_argument(
            "--timeout-seconds",
            type=float,
            default=DEFAULT_BROWSER_RENDER_TIMEOUT_SECONDS,
            help="Maximum time to wait for the Playwright browser render to finish.",
        )
        subparser.add_argument(
            "--no-daemon",
            action="store_true",
            help="Debug only: run Playwright directly instead of using the warm render daemon.",
        )
        add_logging_args(subparser)

    def add_orbit_args(subparser: argparse.ArgumentParser) -> None:
        add_step_input(subparser)
        subparser.add_argument("--output", "--out", "-o", dest="output", type=Path, required=True, help="Output GIF path.")
        subparser.add_argument("--width", type=int, default=None, help="Output GIF width. Defaults from --quality.")
        subparser.add_argument("--height", type=int, default=None, help="Output GIF height. Defaults from --quality.")
        subparser.add_argument("--size", type=int, help="Set both width and height.")
        subparser.add_argument(
            "--background",
            default=_rgb_default(DEFAULT_BACKGROUND_COLOR),
            help="Background RGB as '#rrggbb' or 0..1 comma values.",
        )
        subparser.add_argument("--focus", help="Comma-separated occurrence, name, source, or @cad selectors.")
        subparser.add_argument("--hide", help="Comma-separated occurrence, name, source, or @cad selectors.")
        subparser.add_argument("--preset", choices=PRESETS, default="solid")
        subparser.add_argument(
            "--quality",
            choices=QUALITY_LEVELS,
            default="standard",
            help="Orbit GIF quality profile. Controls default dimensions, frame count, and browser supersampling.",
        )
        subparser.add_argument(
            "--color-by",
            choices=COLOR_BY_MODES,
            default=None,
            help="Color policy: STEP colors, occurrence debug colors, or one neutral color.",
        )
        subparser.add_argument("--edges", choices=EDGE_STYLES, default="thin")
        subparser.add_argument("--axes", action=argparse.BooleanOptionalAction, default=True)
        subparser.add_argument("--render-mode", choices=("solid", "wireframe"), default="solid")
        subparser.add_argument("--hidden-lines", choices=("off", "faint", "all"), default="off")
        subparser.add_argument("--start-azimuth", type=float, default=-45.0, help="Starting orbit azimuth in degrees.")
        subparser.add_argument("--elevation", type=float, default=30.0, help="Orbit camera elevation in degrees.")
        subparser.add_argument("--turns", type=float, default=1.0, help="Number of 360 degree turns across the GIF.")
        subparser.add_argument("--duration-seconds", type=float, default=None, help="Total GIF duration in seconds.")
        subparser.add_argument("--fps", type=float, default=None, help="GIF frame rate. Defaults from --quality.")
        subparser.add_argument("--frames", type=int, default=None, help="Explicit frame count. Overrides duration x fps.")
        subparser.add_argument(
            "--timeout-seconds",
            type=float,
            default=DEFAULT_BROWSER_RENDER_TIMEOUT_SECONDS,
            help="Maximum time to wait for the Playwright browser render to finish.",
        )
        subparser.add_argument(
            "--no-daemon",
            action="store_true",
            help="Debug only: run Playwright directly instead of using the warm render daemon.",
        )
        add_logging_args(subparser)

    three_d = subparsers.add_parser(
        "view",
        help="Render a shaded STEP view.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  render view STEP/part.step --camera iso -o /tmp/part.png\n"
            "  render view STEP/.part.step.glb --camera iso -o /tmp/part.png\n"
            "  render view '@cad[STEP/assembly#o1.2.f10]' --camera top -o /tmp/focus.png\n"
        ),
    )
    add_render_args(three_d)
    three_d.add_argument("--render-mode", choices=("solid", "wireframe"), default="solid")
    three_d.set_defaults(handler=run_render, render_parser=three_d)

    wireframe = subparsers.add_parser("wireframe", help="Render STEP edges.")
    add_render_args(wireframe)
    wireframe.add_argument("--hidden-lines", choices=("off", "faint", "all"), default="off")
    wireframe.set_defaults(handler=run_render, render_parser=wireframe)

    orbit = subparsers.add_parser(
        "orbit",
        help="Render an orbital looping GIF from a STEP view.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  render orbit STEP/part.step -o /tmp/part-orbit.gif\n"
            "  render orbit STEP/part.step -o /tmp/part-hq.gif --quality very-high --fps 24\n"
        ),
    )
    add_orbit_args(orbit)
    orbit.set_defaults(handler=run_render, render_parser=orbit)

    section = subparsers.add_parser("section", help="Render a STEP plane section.")
    add_step_input(section)
    section.add_argument("--output", "--out", "-o", dest="output", type=Path, required=True)
    section.add_argument("--plane", choices=("XY", "XZ", "YZ"), default="XY")
    section.add_argument("--offset", type=float, default=0.0, help="Plane offset in millimeters.")
    section.add_argument("--at", help="Point on the section plane as x,y,z.")
    section.add_argument("--normal", help="Plane normal as x,y,z.")
    section.add_argument("--format", choices=("svg", "png"), help="Output format. Defaults from extension.")
    section.add_argument("--width", type=int, default=1400)
    section.add_argument("--height", type=int, default=900)
    section.add_argument("--size", type=int)
    section.add_argument(
        "--background",
        default=_rgb_default(DEFAULT_BACKGROUND_COLOR),
        help="Background RGB as '#rrggbb' or 0..1 comma values.",
    )
    section.add_argument("--transparent", action="store_true")
    section.add_argument("--focus", help="Comma-separated occurrence, name, source, or @cad selectors.")
    section.add_argument("--hide", help="Comma-separated occurrence, name, source, or @cad selectors.")
    section.add_argument(
        "--color-by",
        choices=COLOR_BY_MODES,
        default=None,
        help="Color policy: neutral technical lines, STEP colors, or occurrence debug colors.",
    )
    section.add_argument("--edges", choices=EDGE_STYLES, default="thin")
    add_logging_args(section)
    section.set_defaults(handler=run_render, render_parser=section)

    list_parts = subparsers.add_parser("list", help="List renderable STEP occurrences.")
    add_step_input(list_parts)
    list_parts.add_argument("--format", choices=("json", "text"), default="json", help="Output format. Default: json.")
    add_logging_args(list_parts)
    list_parts.set_defaults(handler=run_render, render_parser=list_parts)

    daemon = subparsers.add_parser("daemon", help="Manage the warm Playwright render daemon.")
    daemon_subparsers = daemon.add_subparsers(dest="daemon_command", required=True)

    def add_daemon_socket_arg(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--socket", type=Path, help="Override the derived render daemon Unix socket path.")

    daemon_status = daemon_subparsers.add_parser("status", help="Show render daemon status.")
    add_daemon_socket_arg(daemon_status)
    daemon_status.set_defaults(handler=run_daemon_command)

    daemon_stop = daemon_subparsers.add_parser("stop", help="Stop the render daemon.")
    add_daemon_socket_arg(daemon_stop)
    daemon_stop.set_defaults(handler=run_daemon_command)

    daemon_run = daemon_subparsers.add_parser("run", help=argparse.SUPPRESS)
    daemon_run.add_argument("--socket", type=Path, required=True)
    daemon_run.add_argument("--idle-timeout-seconds", type=float, default=RENDER_DAEMON_IDLE_TIMEOUT_SECONDS)
    daemon_run.add_argument("--max-jobs", type=int, default=RENDER_DAEMON_MAX_JOBS)
    daemon_run.set_defaults(handler=run_daemon_command)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command_label = str(getattr(args, "command", "render") or "render")
    logger = CliLogger("render", verbose=bool(getattr(args, "verbose", False)))
    with logger.timed(command_label):
        return int(args.handler(args))


def _render_command(args: argparse.Namespace) -> str:
    return str(getattr(args, "render_command", None) or getattr(args, "command", ""))


def run_render(args: argparse.Namespace) -> int:
    result = run_render_result(args)
    logger = CliLogger("render", verbose=bool(getattr(args, "verbose", False)))
    _log_render_timings(logger, result)
    command = str(result.get("command") or "")
    if command == "list":
        _print_step_scene_part_rows(
            result.get("parts", []),
            output_format=str(getattr(args, "format", "json")),
            quiet=bool(getattr(args, "quiet", False)),
            verbose=bool(getattr(args, "verbose", False)),
        )
        return 0
    if command == "section":
        if not bool(getattr(args, "quiet", False)):
            print(f"saved section: {Path(str(result.get('output', ''))).resolve()}")
        return 0
    if command == "orbit":
        if not bool(getattr(args, "quiet", False)):
            print(f"saved orbit gif: {Path(str(result.get('output', ''))).resolve()}")
        return 0
    for output in result.get("outputs", []):
        if not isinstance(output, dict):
            continue
        label = f"{output.get('camera')} " if len(result.get("outputs", [])) > 1 else ""
        if not bool(getattr(args, "quiet", False)):
            print(f"saved {label}png: {Path(str(output.get('path'))).resolve()}")
    return 0


def _log_render_timings(logger: CliLogger, result: dict[str, object]) -> None:
    if not logger.verbose:
        return
    timings = result.get("timings")
    if not isinstance(timings, dict) or not timings:
        return
    details = ", ".join(f"{key}={value}" for key, value in sorted(timings.items()))
    logger.info(f"renderer timings: {details}")


def render_json_result(
    argv: Sequence[str],
    *,
    scene_provider: Callable[[Path], Any | None] | None = None,
    context_provider: Any | None = None,
    browser_renderer: Callable[[dict[str, object]], dict[str, object]] | None = None,
) -> dict[str, object]:
    parser = build_parser()
    args = parser.parse_args(list(argv))
    return run_render_result(
        args,
        scene_provider=scene_provider,
        context_provider=context_provider,
        browser_renderer=browser_renderer,
    )


def run_render_result(
    args: argparse.Namespace,
    *,
    scene_provider: Callable[[Path], Any | None] | None = None,
    context_provider: Any | None = None,
    browser_renderer: Callable[[dict[str, object]], dict[str, object]] | None = None,
) -> dict[str, object]:
    args.command = _render_command(args)
    parser = getattr(args, "render_parser", None)
    if not isinstance(parser, argparse.ArgumentParser):
        parser = build_parser()
    target = _resolve_render_target(str(args.input), context_provider=context_provider)
    args.input = target.source_path or target.glb_path
    if target.target_focus:
        args.focus = _merge_focus(getattr(args, "focus", None), target.target_focus)
    if args.command == "list":
        scene_parts = load_glb_scene_parts(target, scene_provider=scene_provider)
        scene_parts = filter_scene_parts(
            scene_parts,
            focus=getattr(args, "focus", None),
            hide=getattr(args, "hide", None),
        )
        return {
            "ok": True,
            "command": "list",
            "path": target.display_path,
            "glbPath": relative_render_path(target.glb_path),
            **({"stepPath": relative_render_path(target.source_path)} if target.source_path is not None else {}),
            "parts": _step_scene_part_rows(scene_parts),
        }

    scene_parts = load_glb_scene_parts(target, scene_provider=scene_provider)
    scene_parts = filter_scene_parts(scene_parts, focus=args.focus, hide=args.hide)
    if not scene_parts:
        raise RuntimeError("No GLB occurrences remain after applying focus/hide filters")

    if args.command == "section":
        mesh_instances = mesh_instances_from_glb_parts(scene_parts)
        section = write_section_result(args, mesh_instances)
        return {
            "ok": True,
            "command": "section",
            "path": target.display_path,
            "glbPath": relative_render_path(target.glb_path),
            **({"stepPath": relative_render_path(target.source_path)} if target.source_path is not None else {}),
            "focus": args.focus or "",
            "hide": args.hide or "",
            **section,
        }

    if args.command == "orbit":
        return _run_orbit_render_result(
            target,
            args,
            parser,
            scene_parts,
            browser_renderer=browser_renderer,
        )

    render_jobs = _resolve_render_jobs(args, parser)
    model_color, background_color, edge_style, preset, render_mode, color_by = _resolve_render_options(args)
    browser_job = _build_browser_render_job(
        target,
        args,
        scene_parts,
        render_jobs,
        model_color=model_color,
        background_color=background_color,
        edge_style=edge_style,
        preset=preset,
        render_mode=render_mode,
        color_by=color_by,
    )
    renderer = browser_renderer or _run_browser_render_job
    browser_result = renderer(browser_job)
    outputs = _browser_render_outputs(browser_result, render_jobs, width=int(args.width), height=int(args.height))
    return {
        "ok": True,
        "command": args.command,
        "path": target.display_path,
        "glbPath": relative_render_path(target.glb_path),
        **({"stepPath": relative_render_path(target.source_path)} if target.source_path is not None else {}),
        "focus": args.focus or "",
        "hide": args.hide or "",
        "preset": preset,
        "renderMode": render_mode,
        "colorBy": color_by,
        "edgeStyle": edge_style,
        "background": background_color,
        "modelColor": model_color,
        "renderer": "browser-three",
        "timings": browser_result.get("timings", {}) if isinstance(browser_result, dict) else {},
        "outputs": outputs,
    }


def _resolve_render_target(target: str, *, context_provider: Any | None = None) -> GlbRenderTarget:
    del context_provider
    raw_target = str(target or "").strip()
    if not raw_target:
        raise ValueError("render requires an input target")

    source_path: Path | None = None
    raw_path = Path(raw_target).expanduser()
    resolved_path = raw_path.resolve() if raw_path.is_absolute() else (Path.cwd() / raw_path).resolve()
    if resolved_path.exists() and resolved_path.suffix.lower() == ".glb":
        glb_path = resolved_path
        manifest = read_step_topology_manifest_from_glb(glb_path)
        if manifest is None:
            raise CadRefError(
                "GLB render target does not include readable STEP_topology. "
                "Rerun render with the owning STEP/STP path or @cad[...] target so the regeneration command can be inferred."
            )
        source_path = _step_path_from_manifest(manifest, glb_path=glb_path)
        cad_path = _cad_path_from_step_path(source_path)
        kind = str(manifest.get("entryKind") or "").strip().lower()
        if kind not in {"part", "assembly"}:
            kind = "part"
        artifact = validate_step_topology_artifact(
            ResolvedStepTarget(
                cad_path=cad_path,
                kind=kind,
                source_path=source_path,
                step_path=source_path,
            ),
            glb_path=glb_path,
        )
        manifest = artifact.manifest
        display_path = relative_render_path(glb_path)
    else:
        try:
            resolved_target = resolve_step_target(raw_target)
        except CadRefError as exc:
            raise CadRefError(f"GLB render target could not be resolved from {target!r}: {exc}") from exc
        source_path = resolved_target.step_path.resolve()
        artifact = validate_step_topology_artifact(
            resolved_target,
            require_selector=_render_target_requires_selector_topology(raw_target),
        )
        glb_path = artifact.glb_path.resolve()
        manifest = artifact.manifest
        display_path = relative_render_path(source_path)

    focus_manifest = artifact.selector_bundle.manifest if artifact.selector_bundle is not None else manifest
    target_focus = _selector_focus_from_target(raw_target, glb_path=glb_path, index_manifest=focus_manifest)
    return GlbRenderTarget(
        glb_path=glb_path,
        source_path=source_path,
        display_path=display_path,
        manifest=manifest,
        target_focus=target_focus,
    )


def _step_path_from_manifest(manifest: dict[str, Any], *, glb_path: Path) -> Path:
    colocated_step_path = _colocated_step_path_from_glb(glb_path)
    if colocated_step_path is not None:
        return colocated_step_path

    raw_step_path = str(manifest.get("stepPath") or "").strip()
    if not raw_step_path:
        raise CadRefError(
            "GLB render target STEP_topology does not include stepPath. "
            "Rerun render with the owning STEP/STP path or @cad[...] target so the regeneration command can be inferred."
        )
    step_path = Path(raw_step_path).expanduser()
    candidates = [
        step_path.resolve() if step_path.is_absolute() else (Path.cwd() / step_path).resolve(),
        (glb_path.parent / step_path.name).resolve(),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise CadRefError(
        "GLB render target STEP_topology stepPath does not resolve to an existing STEP/STP file. "
        "Rerun render with the owning STEP/STP path or @cad[...] target so the regeneration command can be inferred."
    )


def _colocated_step_path_from_glb(glb_path: Path) -> Path | None:
    glb_name = glb_path.name
    lower_name = glb_name.lower()
    if glb_name.startswith(".") and (lower_name.endswith(".step.glb") or lower_name.endswith(".stp.glb")):
        candidate = (glb_path.parent / glb_name[1:-4]).resolve()
        return candidate if candidate.is_file() else None

    if glb_name == "model.glb":
        artifact_dir_name = glb_path.parent.name
        lower_artifact_dir_name = artifact_dir_name.lower()
        if artifact_dir_name.startswith(".") and (
            lower_artifact_dir_name.endswith(".step")
            or lower_artifact_dir_name.endswith(".stp")
        ):
            candidate = (glb_path.parent.parent / artifact_dir_name[1:]).resolve()
            return candidate if candidate.is_file() else None

    return None


def _cad_path_from_step_path(step_path: Path) -> str:
    resolved = step_path.resolve()
    try:
        return resolved.relative_to(CAD_ROOT).with_suffix("").as_posix()
    except ValueError:
        return resolved.with_suffix("").as_posix()


def _render_target_requires_selector_topology(target: str) -> bool:
    if not target.strip().startswith("@cad["):
        return False
    selector = _selector_from_cad_ref(target)
    if selector == target:
        return False
    return re.match(r"o\d+(?:\.\d+)*$", selector) is None


def _selector_focus_from_target(
    target: str,
    *,
    glb_path: Path | None = None,
    index_manifest: dict[str, Any] | None = None,
) -> str:
    if not target.strip().startswith("@cad["):
        return ""
    selector = _selector_from_cad_ref(target)
    if selector == target:
        return ""
    occurrence_match = re.match(r"(o\d+(?:\.\d+)*)", selector)
    if occurrence_match:
        return occurrence_match.group(1)
    manifest = index_manifest
    if glb_path is not None and not _manifest_has_selector_tables(manifest or {}):
        bundle = read_step_topology_bundle_from_glb(glb_path)
        if bundle is not None:
            manifest = bundle.manifest
    return _occurrence_id_for_selector(selector, manifest or {})


def _manifest_has_selector_tables(manifest: dict[str, Any]) -> bool:
    return any(isinstance(manifest.get(key), list) for key in ("shapes", "faces", "edges", "vertices"))


def _occurrence_id_for_selector(selector: str, manifest: dict[str, Any]) -> str:
    normalized_selector = selector.strip().lower()
    if not normalized_selector:
        return ""
    selector_kind = normalized_selector[0]
    table_key = {
        "s": "shapes",
        "f": "faces",
        "e": "edges",
        "v": "vertices",
    }.get(selector_kind)
    if table_key:
        matches: list[str] = []
        for row in _manifest_table_rows(manifest, table_key):
            row_id = str(row.get("id") or "").strip().lower()
            if row_id == normalized_selector or row_id.endswith(f".{normalized_selector}"):
                occurrence_id = str(row.get("occurrenceId") or "").strip()
                if occurrence_id:
                    matches.append(occurrence_id)
        unique_matches = sorted(set(matches))
        if len(unique_matches) == 1:
            return unique_matches[0]
    root_occurrences = [
        str(row.get("id") or row.get("occurrenceId") or "").strip()
        for row in _manifest_table_rows(manifest, "occurrences")
        if row.get("parentId") in {None, ""}
    ]
    unique_roots = [occurrence_id for occurrence_id in sorted(set(root_occurrences)) if occurrence_id]
    return unique_roots[0] if len(unique_roots) == 1 else selector


def _manifest_table_rows(manifest: dict[str, Any], table_key: str) -> list[dict[str, Any]]:
    rows = manifest.get(table_key)
    if not isinstance(rows, list):
        return []
    column_key = {
        "occurrences": "occurrenceColumns",
        "shapes": "shapeColumns",
        "faces": "faceColumns",
        "edges": "edgeColumns",
        "vertices": "vertexColumns",
    }.get(table_key, "")
    columns = manifest.get("tables", {}).get(column_key) if isinstance(manifest.get("tables"), dict) else None
    output: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            output.append(row)
        elif isinstance(row, list) and isinstance(columns, list):
            output.append({str(column): row[index] for index, column in enumerate(columns) if index < len(row)})
    return output


def _merge_focus(existing: str | None, target_focus: str) -> str:
    values = [value for value in (str(existing or "").strip(), str(target_focus or "").strip()) if value]
    return ",".join(values)


def _run_orbit_render_result(
    target: GlbRenderTarget,
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    scene_parts: list[GlbScenePart],
    *,
    browser_renderer: Callable[[dict[str, object]], dict[str, object]] | None = None,
) -> dict[str, object]:
    settings = _resolve_orbit_settings(args, parser)
    model_color, background_color, edge_style, preset, render_mode, color_by = _resolve_render_options(args)
    output_path = Path(args.output).expanduser().resolve()
    renderer = browser_renderer or _run_browser_render_job
    gif_started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="cad-render-orbit-") as temp_dir:
        render_jobs = _resolve_orbit_render_jobs(settings, Path(temp_dir))
        args.lock_framing = True
        browser_job = _build_browser_render_job(
            target,
            args,
            scene_parts,
            render_jobs,
            model_color=model_color,
            background_color=background_color,
            edge_style=edge_style,
            preset=preset,
            render_mode=render_mode,
            color_by=color_by,
        )
        browser_result = renderer(browser_job)
        frame_outputs = _browser_render_outputs(
            browser_result,
            render_jobs,
            width=settings.width,
            height=settings.height,
        )
        frame_paths = [Path(str(frame["path"])) for frame in frame_outputs]
        _write_orbit_gif(frame_paths, output_path, frame_duration_ms=settings.frame_duration_ms)
    gif_ms = (time.monotonic() - gif_started) * 1000.0
    timings = browser_result.get("timings", {}) if isinstance(browser_result, dict) else {}
    if not isinstance(timings, dict):
        timings = {}
    return {
        "ok": True,
        "command": "orbit",
        "path": target.display_path,
        "glbPath": relative_render_path(target.glb_path),
        **({"stepPath": relative_render_path(target.source_path)} if target.source_path is not None else {}),
        "focus": args.focus or "",
        "hide": args.hide or "",
        "preset": preset,
        "renderMode": render_mode,
        "colorBy": color_by,
        "edgeStyle": edge_style,
        "background": background_color,
        "modelColor": model_color,
        "renderer": "browser-three",
        "quality": settings.quality,
        "output": output_path.as_posix(),
        "format": "gif",
        "width": settings.width,
        "height": settings.height,
        "frameCount": settings.frame_count,
        "fps": settings.fps,
        "durationSeconds": settings.duration_seconds,
        "frameDurationMs": settings.frame_duration_ms,
        "startAzimuth": settings.start_azimuth,
        "elevation": settings.elevation,
        "turns": settings.turns,
        "timings": {**timings, "gifMs": round(gif_ms, 3)},
    }


def _resolve_orbit_settings(args: argparse.Namespace, parser: argparse.ArgumentParser) -> OrbitSettings:
    output_path = Path(args.output).expanduser()
    if output_path.suffix.lower() != ".gif":
        parser.error("render orbit output must use a .gif extension")
    quality = str(getattr(args, "quality", "standard") or "standard")
    profile = ORBIT_QUALITY_PROFILES[quality]
    width = int(args.size or args.width or profile["width"])
    height = int(args.size or args.height or profile["height"])
    if width <= 0 or height <= 0:
        parser.error("render orbit width and height must be positive")

    fps = _positive_finite_float(
        getattr(args, "fps", None),
        default=float(profile["fps"]),
        label="--fps",
        parser=parser,
    )
    if fps > ORBIT_MAX_FPS:
        parser.error(f"render orbit --fps must be at most {ORBIT_MAX_FPS:g}")

    duration_input = getattr(args, "duration_seconds", None)
    duration_seconds = _positive_finite_float(
        duration_input,
        default=float(profile["duration_seconds"]),
        label="--duration-seconds",
        parser=parser,
    )
    if duration_seconds > ORBIT_MAX_DURATION_SECONDS:
        parser.error(f"render orbit --duration-seconds must be at most {ORBIT_MAX_DURATION_SECONDS:g}")

    if getattr(args, "frames", None) is None:
        frame_count = max(2, int(round(duration_seconds * fps)))
    else:
        frame_count = int(args.frames)
        if frame_count < 2:
            parser.error("render orbit --frames must be at least 2")
        if duration_input is None:
            duration_seconds = frame_count / fps
    if frame_count > ORBIT_MAX_FRAMES:
        parser.error(f"render orbit --frames must be at most {ORBIT_MAX_FRAMES}")
    frame_duration_ms = max(1, int(round((duration_seconds * 1000.0) / frame_count)))

    start_azimuth = _finite_float(getattr(args, "start_azimuth", -45.0), label="--start-azimuth", parser=parser)
    elevation = _finite_float(getattr(args, "elevation", 30.0), label="--elevation", parser=parser)
    if not -89.0 <= elevation <= 89.0:
        parser.error("render orbit --elevation must be between -89 and 89 degrees")
    turns = _positive_finite_float(getattr(args, "turns", 1.0), default=1.0, label="--turns", parser=parser)
    if turns > 10.0:
        parser.error("render orbit --turns must be at most 10")

    args.width = width
    args.height = height
    return OrbitSettings(
        width=width,
        height=height,
        fps=fps,
        frame_count=frame_count,
        duration_seconds=duration_seconds,
        frame_duration_ms=frame_duration_ms,
        start_azimuth=start_azimuth,
        elevation=elevation,
        turns=turns,
        quality=quality,
    )


def _finite_float(value: object, *, label: str, parser: argparse.ArgumentParser) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        parser.error(f"render orbit {label} must be a finite number")
    if not math.isfinite(number):
        parser.error(f"render orbit {label} must be a finite number")
    return number


def _positive_finite_float(
    value: object,
    *,
    default: float,
    label: str,
    parser: argparse.ArgumentParser,
) -> float:
    number = default if value is None else _finite_float(value, label=label, parser=parser)
    if number <= 0.0:
        parser.error(f"render orbit {label} must be positive")
    return number


def _resolve_orbit_render_jobs(settings: OrbitSettings, temp_dir: Path) -> list[tuple[str, Path]]:
    frame_digits = max(4, len(str(settings.frame_count - 1)))
    render_jobs: list[tuple[str, Path]] = []
    for index in range(settings.frame_count):
        azimuth = settings.start_azimuth + (360.0 * settings.turns * index / settings.frame_count)
        camera = f"{azimuth:.6f}:{settings.elevation:.6f}"
        render_jobs.append((camera, temp_dir / f"orbit-frame-{index:0{frame_digits}d}.png"))
    return render_jobs


def _write_orbit_gif(frame_paths: Sequence[Path], output_path: Path, *, frame_duration_ms: int) -> None:
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "render orbit requires Pillow for GIF encoding. "
            "Install CAD skill requirements with: "
            "./.venv/bin/python -m pip install -r .agents/skills/cad/requirements.txt"
        ) from exc
    if not frame_paths:
        raise RuntimeError("render orbit did not produce any frames")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames: list[Any] = []
    paletted_frames: list[Any] = []
    palette: Any | None = None
    try:
        for frame_path in frame_paths:
            with Image.open(frame_path) as image:
                frames.append(image.convert("RGB"))
        palette = _shared_gif_palette(frames, Image)
        dither = getattr(getattr(Image, "Dither", Image), "FLOYDSTEINBERG", 3)
        paletted_frames = [frame.quantize(palette=palette, dither=dither) for frame in frames]
        paletted_frames[0].save(
            output_path,
            save_all=True,
            append_images=paletted_frames[1:],
            duration=frame_duration_ms,
            loop=0,
            optimize=False,
            disposal=2,
        )
    finally:
        for frame in [*frames, *paletted_frames]:
            with contextlib.suppress(Exception):
                frame.close()
        if palette is not None:
            with contextlib.suppress(Exception):
                palette.close()


def _shared_gif_palette(frames: Sequence[Any], image_module: Any) -> Any:
    resampling = getattr(getattr(image_module, "Resampling", image_module), "LANCZOS", 1)
    quantize_method = getattr(getattr(image_module, "Quantize", image_module), "MEDIANCUT", 0)
    samples: list[Any] = []
    atlas: Any | None = None
    try:
        for frame in frames:
            sample = frame.copy()
            sample.thumbnail((160, 160), resampling)
            samples.append(sample)
        width = max(sample.width for sample in samples)
        height = sum(sample.height for sample in samples)
        atlas = image_module.new("RGB", (width, height), (255, 255, 255))
        cursor_y = 0
        for sample in samples:
            atlas.paste(sample, (0, cursor_y))
            cursor_y += sample.height
        return atlas.quantize(colors=256, method=quantize_method)
    finally:
        for sample in samples:
            with contextlib.suppress(Exception):
                sample.close()
        if atlas is not None:
            with contextlib.suppress(Exception):
                atlas.close()


def _resolve_render_jobs(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[tuple[str, Path]]:
    camera_values = args.camera or ["iso"]
    try:
        view_labels = [resolve_view(camera).name for camera in camera_values]
    except ValueError as exc:
        parser.error(str(exc))
    if len(camera_values) > 1:
        if args.output:
            parser.error("Repeated --camera writes multiple files; use --out-dir instead of --output")
        if not args.out_dir:
            parser.error("Repeated --camera requires --out-dir")
        output_stem = _render_output_stem(args.input)
        return [
            (camera_value, args.out_dir / f"{output_stem}-{view_label}.png")
            for camera_value, view_label in zip(camera_values, view_labels, strict=True)
        ]
    if args.out_dir:
        parser.error("--out-dir requires repeated --camera")
    if not args.output:
        parser.error("--output is required")
    return [(camera_values[0], args.output)]


def _resolve_render_options(
    args: argparse.Namespace,
) -> tuple[tuple[float, float, float], tuple[float, float, float], str, str, str, str]:
    width = int(args.size or args.width)
    height = int(args.size or args.height)
    if width <= 0 or height <= 0:
        raise ValueError("render width and height must be positive")
    args.width = width
    args.height = height

    preset = str(args.preset or "solid")
    render_mode = str(getattr(args, "render_mode", "solid") or "solid")
    edge_style = str(args.edges or "thin")
    if args.command == "wireframe" or render_mode == "wireframe":
        render_mode = "wireframe"
        if edge_style == "off":
            edge_style = "thin"
    if preset == "technical" and edge_style == "thin":
        edge_style = "bold"
    if preset == "silhouette":
        render_mode = "wireframe"
        edge_style = "bold"

    model_color = DEFAULT_MODEL_COLOR
    if preset == "clay":
        model_color = (0.74, 0.72, 0.68)
    elif preset == "technical":
        model_color = (0.86, 0.88, 0.90)
    elif preset == "xray":
        model_color = (0.62, 0.76, 0.92)
    background_color = parse_rgb(args.background)
    return model_color, background_color, edge_style, preset, render_mode, _resolve_color_by(args)


def _resolve_color_by(args: argparse.Namespace) -> str:
    explicit = getattr(args, "color_by", None)
    if explicit:
        return str(explicit)
    if getattr(args, "preset", None) == "component":
        return "occurrence"
    if getattr(args, "command", None) in {"wireframe", "section"} or getattr(args, "render_mode", None) == "wireframe":
        return "none"
    return "step"


def _build_browser_render_job(
    target: GlbRenderTarget,
    args: argparse.Namespace,
    scene_parts: list[GlbScenePart],
    render_jobs: list[tuple[str, Path]],
    *,
    model_color: tuple[float, float, float],
    background_color: tuple[float, float, float],
    edge_style: str,
    preset: str,
    render_mode: str,
    color_by: str,
) -> dict[str, object]:
    visible_ids = [part.part_id for part in scene_parts]
    return {
        "schemaVersion": 1,
        "renderer": "render-three",
        "glbPath": target.glb_path.resolve().as_posix(),
        "displayPath": target.display_path,
        "width": int(args.width),
        "height": int(args.height),
        "background": list(background_color),
        "transparent": bool(getattr(args, "transparent", False)),
        "modelColor": list(model_color),
        "visibleOccurrenceIds": visible_ids,
        "partOrder": visible_ids,
        "outputs": [
            {
                "camera": view_name,
                "path": png_out.resolve().as_posix(),
            }
            for view_name, png_out in render_jobs
        ],
        "preset": preset,
        "renderMode": render_mode,
        "colorBy": color_by,
        "edgeStyle": edge_style,
        "quality": str(getattr(args, "quality", "high") or "high"),
        "renderScale": float(QUALITY_RENDER_SCALE[str(getattr(args, "quality", "high") or "high")]),
        "axes": bool(getattr(args, "axes", True)),
        "hiddenLines": str(getattr(args, "hidden_lines", "off") or "off"),
        "lockFraming": bool(getattr(args, "lock_framing", False)),
        "timeoutSeconds": float(
            getattr(args, "timeout_seconds", DEFAULT_BROWSER_RENDER_TIMEOUT_SECONDS)
            or DEFAULT_BROWSER_RENDER_TIMEOUT_SECONDS
        ),
        "useDaemon": not bool(getattr(args, "no_daemon", False)),
    }


def _run_browser_render_job(job: dict[str, object]) -> dict[str, object]:
    if bool(job.get("useDaemon", True)):
        return _run_browser_render_job_via_daemon(job)
    return _run_browser_render_job_once(job)


def _run_browser_render_job_once(job: dict[str, object]) -> dict[str, object]:
    worker = BrowserRenderWorker()
    try:
        return _browser_result_with_daemon_state(worker.render(job), "disabled")
    finally:
        worker.close()


class BrowserRenderWorker:
    def __init__(self) -> None:
        self.playwright_manager: Any | None = None
        self.playwright: Any | None = None
        self.browser: Any | None = None
        self.server: _BrowserRenderServer | None = None
        self.started = False

    def start(self) -> None:
        if self.started:
            return
        _assert_browser_render_assets()
        self.server = _start_browser_render_server()
        try:
            self.playwright_manager = _sync_playwright_context()
            self.playwright = self.playwright_manager.__enter__()
            self.browser = self.playwright.chromium.launch(headless=True)
            self.started = True
        except Exception:
            self.close()
            raise

    def render(self, job: dict[str, object]) -> dict[str, object]:
        timeout_seconds = _browser_render_timeout_seconds(job)
        self.start()
        if self.browser is None or self.server is None:
            raise RuntimeError("render browser worker did not start")
        context: Any | None = None
        result: dict[str, object] | None = None
        self.server.begin_job(job)
        try:
            context = self.browser.new_context(viewport=_browser_window_size(job), device_scale_factor=1)
            page = context.new_page()
            page.goto(
                self.server.url,
                wait_until="load",
                timeout=max(1, int(timeout_seconds * 1000)),
            )
            result = self.server.wait_for_result(timeout_seconds)
        except _BrowserRenderTimeoutError as exc:
            raise RuntimeError(f"render browser renderer timed out after {timeout_seconds:g}s") from exc
        except Exception as exc:
            _raise_browser_render_error(exc, timeout_seconds)
        finally:
            with contextlib.suppress(Exception):
                if context is not None:
                    context.close()
            self.server.clear_job()
        return _validate_browser_render_result(result)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            if self.browser is not None:
                self.browser.close()
        self.browser = None
        with contextlib.suppress(Exception):
            if self.playwright_manager is not None:
                self.playwright_manager.__exit__(None, None, None)
        self.playwright_manager = None
        self.playwright = None
        with contextlib.suppress(Exception):
            if self.server is not None:
                self.server.close()
        self.server = None
        self.started = False


def _validate_browser_render_result(result: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(result, dict):
        raise RuntimeError("render browser renderer returned a non-object JSON result")
    if not result.get("ok"):
        error = result.get("error") or "unknown browser renderer failure"
        raise RuntimeError(f"render browser renderer failed: {error}")
    return result


def _browser_result_with_daemon_state(result: dict[str, object], daemon_state: str) -> dict[str, object]:
    timings = result.get("timings")
    if not isinstance(timings, dict):
        timings = {}
    result["timings"] = {**timings, "daemon": daemon_state}
    return result


def _raise_browser_render_error(exc: Exception, timeout_seconds: float) -> None:
    error_module = exc.__class__.__module__
    if error_module.startswith("playwright") and exc.__class__.__name__ == "TimeoutError":
        raise RuntimeError(f"render browser renderer timed out after {timeout_seconds:g}s") from exc
    if error_module.startswith("playwright"):
        raise RuntimeError(f"render browser renderer failed: {exc}\n{PLAYWRIGHT_INSTALL_HINT}") from exc
    raise exc


def _run_browser_render_job_via_daemon(job: dict[str, object]) -> dict[str, object]:
    timeout_seconds = _browser_render_timeout_seconds(job)
    socket_path = _render_daemon_socket_path()
    started = False
    try:
        response = _send_render_daemon_request(
            socket_path,
            {"command": "render", "job": job},
            timeout_seconds + 5.0,
        )
    except _RenderDaemonConnectionError:
        _remove_stale_render_daemon_socket(socket_path)
        process = _start_render_daemon(socket_path)
        started = True
        _wait_for_render_daemon(socket_path, process)
        response = _send_render_daemon_request(
            socket_path,
            {"command": "render", "job": job},
            timeout_seconds + 5.0,
        )
    if not response.get("ok"):
        raise RuntimeError(f"render daemon failed: {response.get('error') or 'unknown daemon failure'}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("render daemon returned a non-object render result")
    return _browser_result_with_daemon_state(result, "started" if started else "warm")


def _sync_playwright_context() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "render view/wireframe requires the Playwright Python package. "
            "Install CAD skill requirements with: "
            "./.venv/bin/python -m pip install -r .agents/skills/cad/requirements.txt"
        ) from exc
    return sync_playwright()


def _browser_render_timeout_seconds(job: dict[str, object]) -> float:
    raw_timeout = job.get("timeoutSeconds", DEFAULT_BROWSER_RENDER_TIMEOUT_SECONDS)
    try:
        timeout_seconds = float(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("render timeout must be a positive number of seconds") from exc
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0.0:
        raise ValueError("render timeout must be a positive number of seconds")
    return timeout_seconds


def _assert_browser_render_assets() -> None:
    _assert_readable_file(BROWSER_RENDER_HTML, "render.html")
    _assert_readable_file(BROWSER_RENDER_ENTRY, "render_entry.js")
    _assert_readable_file(BROWSER_RENDER_THREE_ROOT / "build" / "three.module.js", "three dependency")
    _assert_readable_file(
        BROWSER_RENDER_THREE_ROOT / "examples" / "jsm" / "loaders" / "GLTFLoader.js",
        "GLTFLoader dependency",
    )


def _assert_readable_file(file_path: Path, label: str) -> None:
    if not file_path.is_file():
        raise RuntimeError(f"render browser renderer cannot read {label}: {file_path}")


class _BrowserRenderTimeoutError(TimeoutError):
    pass


class _BrowserRenderServerState:
    def __init__(self) -> None:
        self.job: dict[str, object] | None = None
        self.result: dict[str, object] | None = None
        self.error: BaseException | None = None
        self.event = threading.Event()
        self.lock = threading.Lock()

    def begin_job(self, job: dict[str, object]) -> None:
        with self.lock:
            self.job = job
            self.result = None
            self.error = None
            self.event = threading.Event()

    def current_job(self) -> dict[str, object]:
        with self.lock:
            if self.job is None:
                raise RuntimeError("render browser server has no active job")
            return self.job

    def set_result(self, result: dict[str, object]) -> None:
        with self.lock:
            if not self.event.is_set():
                self.result = result
                self.event.set()

    def set_error(self, error: BaseException) -> None:
        with self.lock:
            if not self.event.is_set():
                self.error = error
                self.event.set()

    def clear_job(self) -> None:
        with self.lock:
            self.job = None


class _BrowserRenderServer:
    def __init__(
        self,
        http_server: ThreadingHTTPServer,
        state: _BrowserRenderServerState,
        thread: threading.Thread,
    ) -> None:
        self.http_server = http_server
        self.state = state
        self.thread = thread
        host, port = http_server.server_address[:2]
        self.url = f"http://{host}:{port}/render.html"

    def wait_for_result(self, timeout_seconds: float) -> dict[str, object]:
        event = self.state.event
        if not event.wait(timeout_seconds):
            raise _BrowserRenderTimeoutError()
        if self.state.error is not None:
            raise self.state.error
        if self.state.result is None:
            raise RuntimeError("render browser renderer did not return a result")
        return self.state.result

    def begin_job(self, job: dict[str, object]) -> None:
        self.state.begin_job(job)

    def clear_job(self) -> None:
        self.state.clear_job()

    def close(self) -> None:
        self.http_server.shutdown()
        self.http_server.server_close()
        self.thread.join(timeout=1.0)


class _BrowserRenderRequestHandler(BaseHTTPRequestHandler):
    server_version = "CadRenderHTTP/1.0"

    def do_GET(self) -> None:
        state = _request_state(self)
        request_url = urlparse(self.path)
        try:
            if request_url.path == "/render.html":
                self._serve_file(BROWSER_RENDER_HTML, "text/html; charset=utf-8")
                return
            if request_url.path == "/render_entry.js":
                self._serve_file(BROWSER_RENDER_ENTRY, "text/javascript; charset=utf-8")
                return
            if request_url.path == "/job":
                self._write_json(state.current_job())
                return
            if request_url.path == "/asset":
                query = parse_qs(request_url.query)
                asset_values = query.get("path") or []
                if not asset_values:
                    raise ValueError("Missing GLB asset path")
                self._serve_file(Path(asset_values[0]).expanduser().resolve(), "model/gltf-binary")
                return
            if request_url.path.startswith("/node_modules/three/"):
                sub_path = unquote(request_url.path[len("/node_modules/three/") :])
                file_path = (BROWSER_RENDER_THREE_ROOT / sub_path).resolve()
                if not _path_is_relative_to(file_path, BROWSER_RENDER_THREE_ROOT.resolve()):
                    self._send_text(403, "forbidden")
                    return
                self._serve_file(file_path, _mime_for_path(file_path))
                return
            self._send_text(404, "not found")
        except Exception as exc:
            state.set_error(exc)
            self._send_text(500, str(exc))

    def do_POST(self) -> None:
        state = _request_state(self)
        request_url = urlparse(self.path)
        if request_url.path != "/result":
            self._send_text(404, "not found")
            return
        try:
            payload = self.rfile.read(int(self.headers.get("content-length") or "0")).decode("utf-8")
            result = _browser_result_from_payload(json.loads(payload))
            state.set_result(result)
            self._write_json({"ok": True})
        except Exception as exc:
            state.set_error(exc)
            self._send_text(500, str(exc))

    def log_message(self, format: str, *args: object) -> None:
        return

    def _serve_file(self, file_path: Path, content_type: str) -> None:
        if not file_path.is_file():
            raise FileNotFoundError(file_path)
        payload = file_path.read_bytes()
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _write_json(self, value: object) -> None:
        payload = json.dumps(value).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_text(self, status: int, message: str) -> None:
        payload = message.encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "text/plain; charset=utf-8")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _request_state(handler: BaseHTTPRequestHandler) -> _BrowserRenderServerState:
    state = getattr(handler.server, "render_state", None)
    if not isinstance(state, _BrowserRenderServerState):
        raise RuntimeError("render server state is missing")
    return state


def _start_browser_render_server() -> _BrowserRenderServer:
    state = _BrowserRenderServerState()
    http_server = ThreadingHTTPServer(("127.0.0.1", 0), _BrowserRenderRequestHandler)
    setattr(http_server, "render_state", state)
    thread = threading.Thread(target=http_server.serve_forever, name="cad-render-http", daemon=True)
    thread.start()
    return _BrowserRenderServer(http_server, state, thread)


def _browser_result_from_payload(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise RuntimeError("Browser result must be a JSON object")
    if not payload.get("ok"):
        return payload
    result_outputs = payload.get("outputs")
    if not isinstance(result_outputs, list):
        raise RuntimeError("Browser result did not include outputs")
    outputs: list[dict[str, object]] = []
    for output in result_outputs:
        if not isinstance(output, dict):
            raise RuntimeError("Browser result output must be a JSON object")
        output_path = Path(str(output.get("path") or "")).expanduser()
        data_url = str(output.get("dataUrl") or "")
        match = re.match(r"^data:image/png;base64,(.+)$", data_url)
        if not str(output_path) or not match:
            raise RuntimeError("Browser result did not include a valid PNG data URL")
        resolved_path = output_path.resolve()
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_bytes(base64.b64decode(match.group(1), validate=True))
        outputs.append(
            {
                "camera": output.get("camera"),
                "path": resolved_path.as_posix(),
                "width": output.get("width"),
                "height": output.get("height"),
            }
        )
    return {
        "ok": True,
        "outputs": outputs,
        "timings": payload.get("timings", {}) if isinstance(payload.get("timings"), dict) else {},
    }


def _browser_window_size(job: dict[str, object]) -> dict[str, int]:
    outputs = job.get("outputs")
    output_count = len(outputs) if isinstance(outputs, list) else 1
    width = max(320, min(4096, int(job.get("width") or 1400)))
    height = max(240, min(4096, int(job.get("height") or 900)))
    return {
        "width": width,
        "height": max(height, 240 + output_count),
    }


def _mime_for_path(file_path: Path) -> str:
    if file_path.suffix in {".js", ".mjs"}:
        return "text/javascript; charset=utf-8"
    if file_path.suffix == ".json":
        return "application/json; charset=utf-8"
    if file_path.suffix == ".wasm":
        return "application/wasm"
    return mimetypes.guess_type(file_path.as_posix())[0] or "application/octet-stream"


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


class _RenderDaemonConnectionError(RuntimeError):
    pass


class _RenderDaemonProtocolError(RuntimeError):
    pass


def _render_daemon_socket_path() -> Path:
    digest = hashlib.sha256(
        "|".join(
            (
                sys.executable,
                BROWSER_RENDER_DIR.resolve().as_posix(),
                BROWSER_RENDER_THREE_ROOT.resolve().as_posix(),
            )
        ).encode("utf-8")
    ).hexdigest()[:16]
    user_id = os.getuid() if hasattr(os, "getuid") else 0
    socket_root = Path("/tmp") if Path("/tmp").is_dir() else Path(tempfile.gettempdir())
    return socket_root / f"cad-renderd-{user_id}-{digest}.sock"


def _render_daemon_log_path(socket_path: Path) -> Path:
    return socket_path.with_suffix(".log")


def _send_render_daemon_request(
    socket_path: Path,
    request: dict[str, object],
    timeout_seconds: float = RENDER_DAEMON_CONNECT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    if not hasattr(socket, "AF_UNIX"):
        raise RuntimeError("render daemon requires Unix domain socket support")
    payload = dict(request)
    payload["protocolVersion"] = RENDER_DAEMON_PROTOCOL_VERSION
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(max(0.1, float(timeout_seconds)))
            client.connect(socket_path.as_posix())
            stream = client.makefile("rwb")
            stream.write(json.dumps(payload).encode("utf-8") + b"\n")
            stream.flush()
            raw_response = stream.readline()
    except (FileNotFoundError, ConnectionRefusedError, TimeoutError, socket.timeout, OSError) as exc:
        raise _RenderDaemonConnectionError(str(exc)) from exc
    if not raw_response:
        raise _RenderDaemonConnectionError("render daemon closed the socket without a response")
    try:
        response = json.loads(raw_response.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise _RenderDaemonProtocolError("render daemon returned invalid JSON") from exc
    if not isinstance(response, dict):
        raise _RenderDaemonProtocolError("render daemon returned a non-object response")
    if response.get("protocolVersion") != RENDER_DAEMON_PROTOCOL_VERSION:
        raise _RenderDaemonProtocolError("render daemon protocol version mismatch")
    return response


def _remove_stale_render_daemon_socket(socket_path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        socket_path.unlink()


def _start_render_daemon(socket_path: Path) -> subprocess.Popen[bytes]:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = _render_daemon_log_path(socket_path)
    command = [
        sys.executable,
        Path(__file__).resolve().parent.as_posix(),
        "daemon",
        "run",
        "--socket",
        socket_path.as_posix(),
        "--idle-timeout-seconds",
        str(RENDER_DAEMON_IDLE_TIMEOUT_SECONDS),
        "--max-jobs",
        str(RENDER_DAEMON_MAX_JOBS),
    ]
    try:
        log_handle = log_path.open("ab")
    except OSError:
        log_handle = subprocess.DEVNULL  # type: ignore[assignment]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=log_handle,
            close_fds=True,
            cwd=Path.cwd(),
            start_new_session=True,
        )
    except OSError as exc:
        raise RuntimeError(f"render daemon failed to start: {exc}") from exc
    finally:
        if hasattr(log_handle, "close"):
            log_handle.close()
    _STARTED_RENDER_DAEMON_PROCESSES[socket_path.as_posix()] = process
    return process


def _wait_for_render_daemon(
    socket_path: Path,
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float = RENDER_DAEMON_START_TIMEOUT_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            _STARTED_RENDER_DAEMON_PROCESSES.pop(socket_path.as_posix(), None)
            raise RuntimeError(
                f"render daemon exited before it became ready (code={exit_code}). "
                f"Log: {_render_daemon_log_path(socket_path)}"
            )
        try:
            response = _send_render_daemon_request(socket_path, {"command": "status"})
        except (_RenderDaemonConnectionError, _RenderDaemonProtocolError) as exc:
            last_error = exc
            time.sleep(0.05)
            continue
        if response.get("ok"):
            return
        last_error = RuntimeError(str(response.get("error") or "daemon status failed"))
        time.sleep(0.05)
    _terminate_started_render_daemon(socket_path, process)
    raise RuntimeError(
        f"render daemon did not become ready after {timeout_seconds:g}s"
        + (f": {last_error}" if last_error is not None else "")
        + f". Log: {_render_daemon_log_path(socket_path)}"
    )


def _terminate_started_render_daemon(socket_path: Path, process: subprocess.Popen[bytes]) -> None:
    _STARTED_RENDER_DAEMON_PROCESSES.pop(socket_path.as_posix(), None)
    with contextlib.suppress(Exception):
        process.terminate()
    with contextlib.suppress(Exception):
        process.wait(timeout=2.0)
    if process.poll() is None:
        with contextlib.suppress(Exception):
            process.kill()
        with contextlib.suppress(Exception):
            process.wait(timeout=2.0)


def _reap_started_render_daemon(socket_path: Path, *, timeout_seconds: float = 5.0) -> None:
    process = _STARTED_RENDER_DAEMON_PROCESSES.pop(socket_path.as_posix(), None)
    if process is None:
        return
    with contextlib.suppress(Exception):
        process.wait(timeout=timeout_seconds)


def _daemon_response_ok(**fields: object) -> dict[str, object]:
    return {
        "protocolVersion": RENDER_DAEMON_PROTOCOL_VERSION,
        "ok": True,
        **fields,
    }


def _daemon_response_error(error: BaseException | str) -> dict[str, object]:
    return {
        "protocolVersion": RENDER_DAEMON_PROTOCOL_VERSION,
        "ok": False,
        "error": str(error),
    }


def _read_daemon_request(stream: Any) -> dict[str, object]:
    raw_request = stream.readline()
    if not raw_request:
        raise _RenderDaemonProtocolError("empty daemon request")
    try:
        request = json.loads(raw_request.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise _RenderDaemonProtocolError("invalid daemon request JSON") from exc
    if not isinstance(request, dict):
        raise _RenderDaemonProtocolError("daemon request must be a JSON object")
    if request.get("protocolVersion") != RENDER_DAEMON_PROTOCOL_VERSION:
        raise _RenderDaemonProtocolError("daemon protocol version mismatch")
    return request


def _write_daemon_response(stream: Any, response: dict[str, object]) -> None:
    stream.write(json.dumps(response).encode("utf-8") + b"\n")
    stream.flush()


def _serve_render_daemon(
    socket_path: Path,
    *,
    idle_timeout_seconds: float = RENDER_DAEMON_IDLE_TIMEOUT_SECONDS,
    max_jobs: int = RENDER_DAEMON_MAX_JOBS,
    worker_factory: Callable[[], BrowserRenderWorker] = BrowserRenderWorker,
) -> int:
    if not hasattr(socket, "AF_UNIX"):
        raise RuntimeError("render daemon requires Unix domain socket support")
    _remove_stale_render_daemon_socket(socket_path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    worker: BrowserRenderWorker | None = None
    job_count = 0
    stop_requested = False
    try:
        server.bind(socket_path.as_posix())
        with contextlib.suppress(OSError):
            os.chmod(socket_path, 0o600)
        server.listen(1)
        server.settimeout(0.2)
        last_activity = time.monotonic()
        while True:
            if stop_requested:
                break
            if idle_timeout_seconds > 0 and (time.monotonic() - last_activity) >= idle_timeout_seconds:
                break
            if max_jobs > 0 and job_count >= max_jobs:
                break
            try:
                connection, _address = server.accept()
            except socket.timeout:
                continue
            last_activity = time.monotonic()
            with connection:
                stream = connection.makefile("rwb")
                try:
                    request = _read_daemon_request(stream)
                    command = str(request.get("command") or "")
                    if command == "status":
                        response = _daemon_response_ok(
                            pid=os.getpid(),
                            socket=socket_path.as_posix(),
                            jobs=job_count,
                            browserStarted=bool(worker and worker.started),
                            idleTimeoutSeconds=idle_timeout_seconds,
                            maxJobs=max_jobs,
                        )
                    elif command == "stop":
                        stop_requested = True
                        response = _daemon_response_ok(stopped=True)
                    elif command == "render":
                        raw_job = request.get("job")
                        if not isinstance(raw_job, dict):
                            raise _RenderDaemonProtocolError("render daemon request is missing job")
                        if worker is None:
                            worker = worker_factory()
                        response = _daemon_response_ok(result=worker.render(raw_job))
                        job_count += 1
                    else:
                        raise _RenderDaemonProtocolError(f"unknown daemon command: {command}")
                except Exception as exc:
                    response = _daemon_response_error(exc)
                _write_daemon_response(stream, response)
    finally:
        with contextlib.suppress(Exception):
            if worker is not None:
                worker.close()
        with contextlib.suppress(Exception):
            server.close()
        _remove_stale_render_daemon_socket(socket_path)
    return 0


def run_daemon_command(args: argparse.Namespace) -> int:
    socket_path = Path(getattr(args, "socket", None) or _render_daemon_socket_path()).expanduser()
    daemon_command = str(getattr(args, "daemon_command", "") or "")
    if daemon_command == "run":
        return _serve_render_daemon(
            socket_path,
            idle_timeout_seconds=float(getattr(args, "idle_timeout_seconds", RENDER_DAEMON_IDLE_TIMEOUT_SECONDS)),
            max_jobs=int(getattr(args, "max_jobs", RENDER_DAEMON_MAX_JOBS)),
        )
    if daemon_command == "status":
        try:
            response = _send_render_daemon_request(socket_path, {"command": "status"})
        except _RenderDaemonConnectionError:
            print(f"render daemon not running: socket={socket_path}")
            return 1
        if not response.get("ok"):
            print(f"render daemon status failed: {response.get('error') or 'unknown daemon failure'}", file=sys.stderr)
            return 1
        print(
            "render daemon running: "
            f"pid={response.get('pid')} "
            f"jobs={response.get('jobs')} "
            f"browserStarted={str(response.get('browserStarted')).lower()} "
            f"socket={response.get('socket')}"
        )
        return 0
    if daemon_command == "stop":
        try:
            response = _send_render_daemon_request(socket_path, {"command": "stop"})
        except _RenderDaemonConnectionError:
            process = _STARTED_RENDER_DAEMON_PROCESSES.get(socket_path.as_posix())
            if process is not None and process.poll() is None:
                _terminate_started_render_daemon(socket_path, process)
            else:
                _reap_started_render_daemon(socket_path, timeout_seconds=0.1)
            _remove_stale_render_daemon_socket(socket_path)
            print(f"render daemon not running: socket={socket_path}")
            return 0
        if not response.get("ok"):
            print(f"render daemon stop failed: {response.get('error') or 'unknown daemon failure'}", file=sys.stderr)
            return 1
        _reap_started_render_daemon(socket_path)
        print(f"stopped render daemon: socket={socket_path}")
        return 0
    raise RuntimeError(f"Unknown daemon command: {daemon_command}")


def _browser_render_outputs(
    browser_result: dict[str, object],
    render_jobs: list[tuple[str, Path]],
    *,
    width: int,
    height: int,
) -> list[dict[str, object]]:
    result_outputs = browser_result.get("outputs")
    outputs_by_path: dict[str, dict[str, object]] = {}
    if isinstance(result_outputs, list):
        for output in result_outputs:
            if isinstance(output, dict):
                path_value = str(output.get("path") or "")
                if path_value:
                    outputs_by_path[Path(path_value).resolve().as_posix()] = output
    outputs: list[dict[str, object]] = []
    missing: list[str] = []
    for view_name, png_out in render_jobs:
        resolved_path = png_out.resolve()
        if not resolved_path.exists():
            missing.append(resolved_path.as_posix())
            continue
        result_output = outputs_by_path.get(resolved_path.as_posix(), {})
        outputs.append(
            {
                "camera": str(result_output.get("camera") or resolve_view(view_name).name),
                "path": resolved_path.as_posix(),
                "width": int(result_output.get("width") or width),
                "height": int(result_output.get("height") or height),
            }
        )
    if missing:
        raise RuntimeError("Browser renderer did not write expected PNG output(s): " + ", ".join(missing))
    return outputs


def _render_output_stem(input_path: Path) -> str:
    stem = input_path.stem
    cleaned = "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in stem)
    cleaned = cleaned.strip("_")
    return cleaned or "render"


def relative_render_path(path: Path | None) -> str:
    if path is None:
        return ""
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def relative_step_path(step_path: Path) -> str:
    return relative_render_path(step_path)


def _topology_metadata_by_occurrence(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    root = manifest.get("assembly", {}).get("root")
    if not isinstance(root, dict):
        return {}
    metadata: dict[str, dict[str, Any]] = {}
    stack = [root]
    while stack:
        node = stack.pop()
        occurrence_id = str(node.get("occurrenceId") or node.get("id") or "").strip()
        if occurrence_id:
            metadata[occurrence_id] = node
        leaf_part_ids = node.get("leafPartIds")
        if isinstance(leaf_part_ids, list):
            for leaf_part_id in leaf_part_ids:
                leaf_occurrence_id = str(leaf_part_id or "").strip()
                if leaf_occurrence_id:
                    metadata.setdefault(leaf_occurrence_id, node)
        children = node.get("children")
        if isinstance(children, list):
            stack.extend(child for child in reversed(children) if isinstance(child, dict))
    return metadata


def _metadata_for_occurrence(
    occurrence_id: str,
    metadata_by_occurrence: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    current = occurrence_id
    while current:
        metadata = metadata_by_occurrence.get(current)
        if metadata:
            return metadata
        if "." not in current:
            break
        current = current.rsplit(".", 1)[0]
    return {}


def _color_rgb_from_rgba(rgba: tuple[float, ...] | None) -> tuple[float, float, float] | None:
    if rgba is None or len(rgba) < 3:
        return None
    return (float(rgba[0]), float(rgba[1]), float(rgba[2]))


def load_glb_scene_parts(
    target: GlbRenderTarget | Path,
    *,
    scene_provider: Callable[[Path], Any | None] | None = None,
) -> list[GlbScenePart]:
    resolved_target = target if isinstance(target, GlbRenderTarget) else _resolve_render_target(str(target))
    scene = scene_provider(resolved_target.glb_path) if scene_provider is not None else None
    if scene is None:
        scene = _load_trimesh_scene(resolved_target.glb_path)
    return load_glb_scene_parts_from_scene(resolved_target, scene)


def load_glb_scene_parts_from_scene(target: GlbRenderTarget, scene: Any) -> list[GlbScenePart]:
    metadata_by_occurrence = _topology_metadata_by_occurrence(target.manifest)
    parts: list[GlbScenePart] = []
    for node_name in _trimesh_scene_nodes_with_geometry(scene):
        occurrence_id = _occurrence_id_from_trimesh_node(scene, node_name)
        if not occurrence_id:
            continue
        transform, geometry_name = scene.graph[node_name]
        if geometry_name is None:
            continue
        geometry = scene.geometry.get(geometry_name)
        if geometry is None:
            continue
        metadata = _metadata_for_occurrence(occurrence_id, metadata_by_occurrence)
        source_name = str(metadata.get("sourceName") or metadata.get("sourcePath") or "").strip()
        cad_name = _cad_name_from_trimesh_node(scene, node_name)
        display_name = str(
            metadata.get("displayName")
            or metadata.get("instancePath")
            or source_name
            or cad_name
            or node_name
            or occurrence_id
        ).strip()
        if display_name == occurrence_id and occurrence_id == "o1":
            display_name = Path(target.display_path).stem
        source_path = str(metadata.get("sourcePath") or "").strip()
        parts.append(
            GlbScenePart(
                scene=scene,
                node_name=str(node_name),
                geometry_name=str(geometry_name),
                transform=np.asarray(transform, dtype=np.float64),
                part_id=occurrence_id,
                occurrence_id=occurrence_id,
                name=display_name,
                source_name=source_name,
                source_path=source_path,
                color_rgb=_mesh_material_color(geometry),
            )
        )
    return parts


def _load_trimesh_scene(glb_path: Path) -> Any:
    try:
        import trimesh
    except ImportError as exc:
        raise RuntimeError("render GLB mode requires the trimesh Python package") from exc
    try:
        return trimesh.load(glb_path, file_type="glb", force="scene")
    except Exception as exc:
        raise ValueError(f"Failed to load GLB scene: {relative_render_path(glb_path)}") from exc


def _trimesh_scene_nodes_with_geometry(scene: Any) -> tuple[str, ...]:
    nodes = getattr(getattr(scene, "graph", None), "nodes_geometry", ())
    return tuple(str(node) for node in nodes)


def _occurrence_id_from_trimesh_node(scene: Any, node_name: str) -> str:
    graph = getattr(scene, "graph", None)
    cad_occurrence_id = ""
    try:
        metadata = graph[node_name][2]  # Older trimesh versions may expose node metadata here.
    except Exception:
        metadata = None
    if isinstance(metadata, dict):
        cad_occurrence_id = str(
            metadata.get("cadOccurrenceId")
            or metadata.get("extras", {}).get("cadOccurrenceId")
            or ""
        ).strip()
    return cad_occurrence_id or str(node_name).strip()


def _cad_name_from_trimesh_node(scene: Any, node_name: str) -> str:
    graph = getattr(scene, "graph", None)
    try:
        metadata = graph[node_name][2]
    except Exception:
        metadata = None
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("cadName") or metadata.get("extras", {}).get("cadName") or "").strip()


def _mesh_material_color(mesh: Any) -> tuple[float, float, float] | None:
    visual = getattr(mesh, "visual", None)
    material = getattr(visual, "material", None)
    diffuse = getattr(material, "diffuse", None)
    if diffuse is not None and len(diffuse) >= 3:
        values = [float(channel) for channel in diffuse[:3]]
        if any(value > 1.0 for value in values):
            values = [value / 255.0 for value in values]
        return (values[0], values[1], values[2])
    try:
        colors = np.asarray(visual.face_colors, dtype=np.float32)
    except Exception:
        colors = np.empty((0, 4), dtype=np.float32)
    if colors.size and colors.shape[1] >= 3:
        rgb = colors[0, :3]
        if np.all(np.isfinite(rgb)):
            if np.max(rgb) > 1.0:
                rgb = rgb / 255.0
            return (float(rgb[0]), float(rgb[1]), float(rgb[2]))
    return None


def _step_scene_part_rows(parts: list[GlbScenePart]) -> list[dict[str, object]]:
    return [
        {
            "id": part.part_id,
            "occurrenceId": part.occurrence_id,
            "name": part.name,
            "sourceName": part.source_name,
            "sourcePath": part.source_path,
        }
        for part in parts
    ]


def _print_step_scene_part_rows(
    rows: object,
    *,
    output_format: str = "json",
    quiet: bool = False,
    verbose: bool = False,
) -> None:
    normalized_rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    if output_format == "json":
        print(json.dumps(normalized_rows, indent=2))
        return
    if not normalized_rows:
        print("No renderable STEP occurrences found.")
        return
    if quiet:
        for row in normalized_rows:
            print(row["id"])
        return
    print("id\tname\tsource")
    for row in normalized_rows:
        source = row["sourcePath"] or row["sourceName"]
        if verbose:
            print(f"{row['id']}\t{row['name']}\t{source}\t{row['occurrenceId']}")
        else:
            print(f"{row['id']}\t{row['name']}\t{source}")


def _split_selector_tokens(raw_value: str | None) -> tuple[str, ...]:
    if not raw_value:
        return ()
    return tuple(part.strip() for part in raw_value.split(",") if part.strip())


def _selector_from_cad_ref(token: str) -> str:
    match = re.search(r"#([^\]]+)", token)
    if not match:
        return token
    selector = match.group(1).strip()
    occurrence_match = re.match(r"(o\d+(?:\.\d+)*)", selector)
    return occurrence_match.group(1) if occurrence_match else selector


def _normalized_selector(token: str) -> tuple[str, str]:
    value = token.strip()
    if value.startswith("@cad["):
        value = _selector_from_cad_ref(value)
    if ":" in value:
        prefix, rest = value.split(":", 1)
        return prefix.strip().lower(), rest.strip().lower()
    return "", value.lower()


def _part_matches_selector(part: GlbScenePart, token: str) -> bool:
    prefix, value = _normalized_selector(token)
    if not value:
        return False
    occurrence_id = part.occurrence_id.lower()
    names = {
        part.name.lower(),
        part.source_name.lower(),
        part.source_path.lower(),
    }
    if prefix in {"id", "occurrence", "occurrenceid"}:
        return occurrence_id == value or occurrence_id.startswith(f"{value}.")
    if prefix == "name":
        return value in {part.name.lower(), part.source_name.lower()}
    if prefix == "source":
        source_path = part.source_path.lower()
        source_name = part.source_name.lower()
        return source_path == value or source_path.endswith(value) or source_name == value
    if occurrence_id == value or occurrence_id.startswith(f"{value}."):
        return True
    return value in names


def _matching_part_ids(parts: list[GlbScenePart], tokens: tuple[str, ...]) -> set[str]:
    matches: set[str] = set()
    unmatched: list[str] = []
    for token in tokens:
        token_matches = {part.part_id for part in parts if _part_matches_selector(part, token)}
        if token_matches:
            matches.update(token_matches)
        else:
            unmatched.append(token)
    if unmatched:
        unresolved = ", ".join(unmatched)
        raise ValueError(f"Unresolved render selector(s): {unresolved}. Run 'render list <target>'.")
    return matches


def filter_scene_parts(parts: list[GlbScenePart], *, focus: str | None, hide: str | None) -> list[GlbScenePart]:
    focus_tokens = _split_selector_tokens(focus)
    hide_tokens = _split_selector_tokens(hide)
    selected = parts
    if focus_tokens:
        focus_ids = _matching_part_ids(parts, focus_tokens)
        selected = [part for part in selected if part.part_id in focus_ids]
    if hide_tokens:
        hide_ids = _matching_part_ids(parts, hide_tokens)
        selected = [part for part in selected if part.part_id not in hide_ids]
    return selected


def mesh_instances_from_glb_parts(parts: list[GlbScenePart]) -> list[MeshInstance]:
    if not parts:
        return []
    instances: list[MeshInstance] = []
    for part in parts:
        instances.append(_mesh_instance_from_glb_part(part))
    return [instance for instance in instances if _instance_has_geometry(instance)]


def _mesh_instance_from_glb_part(part: GlbScenePart) -> MeshInstance:
    mesh = part.scene.geometry.get(part.geometry_name)
    if mesh is None:
        vertices = np.empty((0, 3), dtype=np.float64)
        triangles = np.empty((0, 3), dtype=np.int64)
        face_colors = None
    else:
        vertices = _transformed_glb_vertices(np.asarray(mesh.vertices, dtype=np.float64), part.transform)
        triangles = np.asarray(mesh.faces, dtype=np.int64).reshape((-1, 3))
        face_colors = _glb_face_color_array(mesh, triangles.shape[0])
    return MeshInstance(
        vertices=vertices,
        triangles=triangles,
        color_rgb=part.color_rgb,
        face_colors_rgb=face_colors,
        part_id=part.part_id,
        name=part.name,
        source_name=part.source_name,
        source_path=part.source_path,
    )


def _transformed_glb_vertices(vertices: np.ndarray, transform: np.ndarray) -> np.ndarray:
    if vertices.size <= 0:
        return np.empty((0, 3), dtype=np.float64)
    if transform.shape == (4, 4):
        homogeneous = np.ones((vertices.shape[0], 4), dtype=np.float64)
        homogeneous[:, :3] = vertices
        vertices = (homogeneous @ transform.T)[:, :3]
    return vertices * GLB_TO_CAD_SCALE


def _glb_face_color_array(mesh: Any, triangle_count: int) -> np.ndarray | None:
    visual = getattr(mesh, "visual", None)
    try:
        colors = np.asarray(visual.face_colors, dtype=np.float32)
    except Exception:
        colors = np.empty((0, 4), dtype=np.float32)
    if colors.shape[0] == triangle_count and colors.shape[1] >= 3:
        rgb = colors[:, :3].copy()
        if np.nanmax(rgb) > 1.0:
            rgb = rgb / 255.0
        return rgb
    color = _mesh_material_color(mesh)
    if color is None:
        return None
    return np.tile(np.asarray(color, dtype=np.float32), (triangle_count, 1))


def _face_color_array(colors: list[tuple[float, float, float] | None]) -> np.ndarray | None:
    if not any(color is not None for color in colors):
        return None
    array = np.full((len(colors), 3), np.nan, dtype=np.float32)
    for index, color in enumerate(colors):
        if color is not None:
            array[index] = color
    return array


def write_section_result(args: argparse.Namespace, mesh_instances: list[MeshInstance]) -> dict[str, object]:
    width = int(args.size or args.width)
    height = int(args.size or args.height)
    if width <= 0 or height <= 0:
        raise ValueError("render width and height must be positive")
    background_color = parse_rgb(args.background)
    point, normal, basis_u, basis_v = _section_plane(args)
    segments = _section_segments(
        mesh_instances,
        point=point,
        normal=normal,
        basis_u=basis_u,
        basis_v=basis_v,
        color_by=_resolve_color_by(args),
    )
    output_format = args.format or args.output.suffix.lower().lstrip(".") or "svg"
    if output_format == "svg":
        _write_section_svg(segments, args.output, edge_style=args.edges)
    elif output_format == "png":
        image = _render_section_png(
            segments,
            width=width,
            height=height,
            background_color=background_color,
            edge_style=args.edges,
        )
        if args.transparent:
            image = _transparent_background(image, background_color)
        _write_png(image, args.output)
    else:
        raise ValueError(f"Unsupported section output format: {output_format}")
    return {
        "output": args.output.resolve().as_posix(),
        "format": output_format,
        "width": width,
        "height": height,
        "plane": str(args.plane or "").upper() if not args.normal else "",
        "offset": float(args.offset or 0.0),
        "normal": args.normal or "",
        "at": args.at or "",
    }


def _parse_vector3(raw_value: str, *, field_name: str) -> np.ndarray:
    parts = [part.strip() for part in raw_value.split(",")]
    if len(parts) != 3:
        raise ValueError(f"{field_name} must be x,y,z")
    try:
        vector = np.asarray([float(part) for part in parts], dtype=np.float64)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be numeric x,y,z") from exc
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{field_name} must be finite x,y,z")
    return vector


def _section_plane(args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if args.normal:
        normal = _normalize(_parse_vector3(args.normal, field_name="--normal"))
        point = _parse_vector3(args.at, field_name="--at") if args.at else np.zeros(3, dtype=np.float64)
        fallback = np.asarray((0.0, 1.0, 0.0), dtype=np.float64)
        if abs(float(np.dot(normal, fallback))) > 0.9:
            fallback = np.asarray((1.0, 0.0, 0.0), dtype=np.float64)
        basis_u = _normalize(np.cross(fallback, normal))
        basis_v = _normalize(np.cross(normal, basis_u))
        return point, normal, basis_u, basis_v

    plane = str(args.plane or "XY").upper()
    offset = float(args.offset or 0.0)
    if plane == "XY":
        return (
            np.asarray((0.0, 0.0, offset), dtype=np.float64),
            np.asarray((0.0, 0.0, 1.0), dtype=np.float64),
            np.asarray((1.0, 0.0, 0.0), dtype=np.float64),
            np.asarray((0.0, 1.0, 0.0), dtype=np.float64),
        )
    if plane == "XZ":
        return (
            np.asarray((0.0, offset, 0.0), dtype=np.float64),
            np.asarray((0.0, 1.0, 0.0), dtype=np.float64),
            np.asarray((1.0, 0.0, 0.0), dtype=np.float64),
            np.asarray((0.0, 0.0, 1.0), dtype=np.float64),
        )
    return (
        np.asarray((offset, 0.0, 0.0), dtype=np.float64),
        np.asarray((1.0, 0.0, 0.0), dtype=np.float64),
        np.asarray((0.0, 1.0, 0.0), dtype=np.float64),
        np.asarray((0.0, 0.0, 1.0), dtype=np.float64),
    )


def _section_segments(
    mesh_instances: list[MeshInstance],
    *,
    point: np.ndarray,
    normal: np.ndarray,
    basis_u: np.ndarray,
    basis_v: np.ndarray,
    color_by: str,
) -> list[tuple[np.ndarray, np.ndarray, tuple[float, float, float]]]:
    segments: list[tuple[np.ndarray, np.ndarray, tuple[float, float, float]]] = []
    epsilon = 1e-7
    for instance_index, instance in enumerate(mesh_instances):
        instance_color = _color_for_policy(
            instance_index,
            instance,
            default_color=TECHNICAL_LINE_COLOR,
            count=len(mesh_instances),
            color_by=color_by,
        )
        for triangle_index, triangle in enumerate(instance.triangles):
            color = (
                _mesh_face_or_instance_color(instance, triangle_index, instance_color)
                if color_by == "step"
                else instance_color
            )
            vertices = instance.vertices[[int(triangle[0]), int(triangle[1]), int(triangle[2])]]
            distances = (vertices - point) @ normal
            if np.all(np.abs(distances) <= epsilon):
                continue
            intersections: list[np.ndarray] = []
            for start_index, end_index in ((0, 1), (1, 2), (2, 0)):
                start = vertices[start_index]
                end = vertices[end_index]
                start_distance = float(distances[start_index])
                end_distance = float(distances[end_index])
                if abs(start_distance) <= epsilon:
                    intersections.append(start)
                if start_distance * end_distance < -epsilon:
                    t = start_distance / (start_distance - end_distance)
                    intersections.append(start + ((end - start) * t))
                if abs(end_distance) <= epsilon:
                    intersections.append(end)
            unique: list[np.ndarray] = []
            seen: set[tuple[int, int, int]] = set()
            for candidate in intersections:
                key = tuple(int(round(float(value) / 1e-6)) for value in candidate)
                if key in seen:
                    continue
                seen.add(key)
                unique.append(candidate)
            if len(unique) < 2:
                continue
            start_2d = np.asarray((float(np.dot(unique[0], basis_u)), float(np.dot(unique[0], basis_v))), dtype=np.float64)
            end_2d = np.asarray((float(np.dot(unique[1], basis_u)), float(np.dot(unique[1], basis_v))), dtype=np.float64)
            if float(np.linalg.norm(end_2d - start_2d)) > 1e-6:
                segments.append((start_2d, end_2d, color))
    return segments


def _mesh_face_or_instance_color(
    instance: MeshInstance,
    face_index: int,
    instance_color: tuple[float, float, float],
) -> tuple[float, float, float]:
    face_colors = instance.face_colors_rgb
    if face_colors is None or face_index >= face_colors.shape[0]:
        return instance_color
    face_color = face_colors[face_index]
    if not np.all(np.isfinite(face_color)):
        return instance_color
    return (float(face_color[0]), float(face_color[1]), float(face_color[2]))


def _section_bounds(
    segments: list[tuple[np.ndarray, np.ndarray, tuple[float, float, float]]],
) -> tuple[float, float, float, float]:
    if not segments:
        return (-1.0, -1.0, 1.0, 1.0)
    points = np.concatenate([np.vstack((start, end)) for start, end, _color in segments], axis=0)
    min_x = float(points[:, 0].min())
    max_x = float(points[:, 0].max())
    min_y = float(points[:, 1].min())
    max_y = float(points[:, 1].max())
    if abs(max_x - min_x) <= 1e-9:
        max_x += 1.0
        min_x -= 1.0
    if abs(max_y - min_y) <= 1e-9:
        max_y += 1.0
        min_y -= 1.0
    return min_x, min_y, max_x, max_y


def _write_section_svg(
    segments: list[tuple[np.ndarray, np.ndarray, tuple[float, float, float]]],
    output_path: Path,
    *,
    edge_style: str,
) -> None:
    min_x, min_y, max_x, max_y = _section_bounds(segments)
    padding = max(max_x - min_x, max_y - min_y) * 0.04
    stroke_width = 0.7 if edge_style == "bold" else 0.35
    output_path.parent.mkdir(parents=True, exist_ok=True)
    view_box = f"{min_x - padding:.6g} {min_y - padding:.6g} {(max_x - min_x) + (2 * padding):.6g} {(max_y - min_y) + (2 * padding):.6g}"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_box}" fill="none" stroke-linecap="round" stroke-linejoin="round">',
    ]
    for start, end, color in segments:
        red, green, blue = _rgb_u8(color)
        lines.append(
            f'<line x1="{start[0]:.6g}" y1="{start[1]:.6g}" x2="{end[0]:.6g}" y2="{end[1]:.6g}" '
            f'stroke="#{red:02x}{green:02x}{blue:02x}" stroke-width="{stroke_width:.6g}" />'
        )
    lines.append("</svg>")
    output_path.write_text("\n".join(lines) + "\n")


def _render_section_png(
    segments: list[tuple[np.ndarray, np.ndarray, tuple[float, float, float]]],
    *,
    width: int,
    height: int,
    background_color: tuple[float, float, float],
    edge_style: str,
) -> np.ndarray:
    background_rgb = np.asarray(_rgb_u8(background_color), dtype=np.uint8)
    image = np.empty((height, width, 3), dtype=np.uint8)
    image[:, :, :] = background_rgb
    min_x, min_y, max_x, max_y = _section_bounds(segments)
    available_width = max(1.0, width - (2.0 * BASE_MARGIN_PX))
    available_height = max(1.0, height - (2.0 * BASE_MARGIN_PX))
    scale = min(available_width / max(max_x - min_x, 1e-9), available_height / max(max_y - min_y, 1e-9))
    radius_px = 2 if edge_style == "bold" else 1
    for start, end, color in segments:
        start_px = np.asarray(
            (
                BASE_MARGIN_PX + ((start[0] - min_x) * scale),
                height - (BASE_MARGIN_PX + ((start[1] - min_y) * scale)),
            ),
            dtype=np.float64,
        )
        end_px = np.asarray(
            (
                BASE_MARGIN_PX + ((end[0] - min_x) * scale),
                height - (BASE_MARGIN_PX + ((end[1] - min_y) * scale)),
            ),
            dtype=np.float64,
        )
        _draw_flat_segment(
            image=image,
            start=start_px,
            end=end_px,
            color=np.asarray(_rgb_u8(color), dtype=np.uint8),
            radius_px=radius_px,
        )
    return _crop_to_content(image, background_rgb)


def _instance_has_geometry(instance: MeshInstance) -> bool:
    return instance.vertices.size > 0 and instance.triangles.size > 0


def _normalize(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if length <= 1e-9:
        raise ValueError(f"Cannot normalize near-zero vector: {vector}")
    return vector / length


def _color_for_policy(
    index: int,
    instance: MeshInstance,
    *,
    default_color: tuple[float, float, float],
    count: int,
    color_by: str,
) -> tuple[float, float, float]:
    if color_by == "step":
        return instance.color_rgb or default_color
    if color_by == "none":
        return default_color
    if color_by == "occurrence":
        if count <= 1:
            return default_color
        return FALLBACK_COMPONENT_COLORS[index % len(FALLBACK_COMPONENT_COLORS)]
    raise ValueError(f"Unknown color policy: {color_by}")


def _face_shading(view_points: np.ndarray, triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    tri_points = view_points[triangles]
    normals = np.cross(tri_points[:, 1] - tri_points[:, 0], tri_points[:, 2] - tri_points[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    safe_lengths = np.where(lengths > 1e-9, lengths, 1.0)
    normals = normals / safe_lengths[:, None]

    oriented = normals.copy()
    oriented[oriented[:, 2] < 0.0] *= -1.0
    light_dir = _normalize(np.asarray((-0.30, 0.45, 1.0), dtype=np.float64))
    brightness = 0.38 + (0.58 * np.clip(oriented @ light_dir, 0.0, 1.0)) + (0.08 * np.clip(oriented[:, 2], 0.0, 1.0))
    return normals, np.clip(brightness, 0.25, 1.0)


def _feature_edges(triangles: np.ndarray, face_normals: np.ndarray) -> tuple[tuple[int, int], ...]:
    edge_faces: dict[tuple[int, int], list[int]] = {}
    for face_index, triangle in enumerate(triangles):
        a, b, c = (int(triangle[0]), int(triangle[1]), int(triangle[2]))
        for start, end in ((a, b), (b, c), (c, a)):
            edge = (start, end) if start < end else (end, start)
            edge_faces.setdefault(edge, []).append(face_index)

    cosine_threshold = math.cos(math.radians(FEATURE_EDGE_ANGLE_DEG))
    feature_edges: list[tuple[int, int]] = []
    for edge, incident_faces in edge_faces.items():
        if len(incident_faces) == 1:
            feature_edges.append(edge)
            continue
        if len(incident_faces) > 2:
            feature_edges.append(edge)
            continue
        first, second = incident_faces
        normal_a = face_normals[first]
        normal_b = face_normals[second]
        if float(np.dot(normal_a, normal_b)) <= cosine_threshold:
            feature_edges.append(edge)
            continue
        if (normal_a[2] >= 0.0) != (normal_b[2] >= 0.0):
            feature_edges.append(edge)
    feature_edges.sort()
    return tuple(feature_edges)


def _depth_range(mesh_instances: list[ProjectedMeshInstance]) -> tuple[float, float]:
    values = np.concatenate([instance.view_points[:, 2] for instance in mesh_instances if instance.view_points.size])
    if values.size <= 0:
        return (0.0, 1.0)
    depth_min = float(values.min())
    depth_max = float(values.max())
    if abs(depth_max - depth_min) <= 1e-9:
        depth_max = depth_min + 1.0
    return depth_min, depth_max


def _rasterize_faces(
    image: np.ndarray,
    depth_buffer: np.ndarray,
    instance: ProjectedMeshInstance,
    *,
    preset: str,
    depth_min: float,
    depth_max: float,
) -> None:
    instance_color = np.asarray(_rgb_u8(instance.color_rgb), dtype=np.float32)
    triangle_count = instance.triangles.shape[0]
    for face_index in range(triangle_count):
        triangle = instance.triangles[face_index]
        indices = (int(triangle[0]), int(triangle[1]), int(triangle[2]))
        screen_triangle = instance.screen_points[list(indices)]
        view_triangle = instance.view_points[list(indices)]
        if preset == "depth-prepass":
            rgb = image[0, 0]
        elif preset == "normals":
            normal = instance.face_normals[face_index]
            rgb = np.asarray(np.clip(np.rint((normal + 1.0) * 127.5), 0, 255), dtype=np.uint8)
        elif preset == "depth":
            z_value = float(view_triangle[:, 2].mean())
            depth_t = (z_value - depth_min) / max(depth_max - depth_min, 1e-9)
            level = int(round(255.0 * max(0.0, min(1.0, depth_t))))
            rgb = np.asarray((level, level, level), dtype=np.uint8)
        elif preset == "xray":
            base_color = _face_or_instance_color(instance, face_index, instance_color)
            shaded = np.clip(np.rint(base_color * (0.55 + (0.30 * instance.face_brightness[face_index]))), 0, 255)
            rgb = np.asarray(shaded, dtype=np.uint8)
        else:
            base_color = _face_or_instance_color(instance, face_index, instance_color)
            rgb = np.asarray(np.clip(np.rint(base_color * instance.face_brightness[face_index]), 0, 255), dtype=np.uint8)
        _rasterize_triangle(
            image=image,
            depth_buffer=depth_buffer,
            screen_triangle=screen_triangle,
            view_triangle=view_triangle,
            rgb=rgb,
        )


def _face_or_instance_color(
    instance: ProjectedMeshInstance,
    face_index: int,
    instance_color: np.ndarray,
) -> np.ndarray:
    face_colors = instance.face_colors_rgb
    if face_colors is None or face_index >= face_colors.shape[0]:
        return instance_color
    face_color = face_colors[face_index]
    if not np.all(np.isfinite(face_color)):
        return instance_color
    return np.asarray(_rgb_u8((float(face_color[0]), float(face_color[1]), float(face_color[2]))), dtype=np.float32)


def _rasterize_triangle(
    *,
    image: np.ndarray,
    depth_buffer: np.ndarray,
    screen_triangle: np.ndarray,
    view_triangle: np.ndarray,
    rgb: np.ndarray,
) -> None:
    x_coords = screen_triangle[:, 0]
    y_coords = screen_triangle[:, 1]
    min_x = max(int(math.floor(float(x_coords.min()))), 0)
    max_x = min(int(math.ceil(float(x_coords.max()))), image.shape[1] - 1)
    min_y = max(int(math.floor(float(y_coords.min()))), 0)
    max_y = min(int(math.ceil(float(y_coords.max()))), image.shape[0] - 1)
    if min_x > max_x or min_y > max_y:
        return

    p0, p1, p2 = screen_triangle
    denominator = ((p1[1] - p2[1]) * (p0[0] - p2[0])) + ((p2[0] - p1[0]) * (p0[1] - p2[1]))
    if abs(float(denominator)) <= 1e-9:
        return

    x_range = np.arange(min_x, max_x + 1, dtype=np.float32) + 0.5
    y_range = np.arange(min_y, max_y + 1, dtype=np.float32) + 0.5
    grid_x, grid_y = np.meshgrid(x_range, y_range)

    w0 = (((p1[1] - p2[1]) * (grid_x - p2[0])) + ((p2[0] - p1[0]) * (grid_y - p2[1]))) / denominator
    w1 = (((p2[1] - p0[1]) * (grid_x - p2[0])) + ((p0[0] - p2[0]) * (grid_y - p2[1]))) / denominator
    w2 = 1.0 - w0 - w1

    epsilon = 1e-5
    inside = (w0 >= -epsilon) & (w1 >= -epsilon) & (w2 >= -epsilon)
    if not np.any(inside):
        return

    z0, z1, z2 = (float(view_triangle[0, 2]), float(view_triangle[1, 2]), float(view_triangle[2, 2]))
    interpolated_depth = (w0 * z0) + (w1 * z1) + (w2 * z2)
    depth_patch = depth_buffer[min_y : max_y + 1, min_x : max_x + 1]
    update_mask = inside & (interpolated_depth >= (depth_patch - 1e-4))
    if not np.any(update_mask):
        return

    image_patch = image[min_y : max_y + 1, min_x : max_x + 1]
    image_patch[update_mask] = rgb
    depth_patch[update_mask] = interpolated_depth[update_mask]


def _rasterize_edges(
    image: np.ndarray,
    depth_buffer: np.ndarray,
    instance: ProjectedMeshInstance,
    edges: tuple[tuple[int, int], ...],
    *,
    radius_px: int,
) -> None:
    edge_color = np.asarray(_edge_rgb(instance.color_rgb), dtype=np.uint8)
    for start, end in edges:
        screen_start = instance.screen_points[start]
        screen_end = instance.screen_points[end]
        depth_start = float(instance.view_points[start, 2])
        depth_end = float(instance.view_points[end, 2])
        _draw_depth_tested_segment(
            image=image,
            depth_buffer=depth_buffer,
            start=screen_start,
            end=screen_end,
            depth_start=depth_start,
            depth_end=depth_end,
            color=edge_color,
            radius_px=radius_px,
        )


def _rasterize_flat_edges(
    image: np.ndarray,
    instance: ProjectedMeshInstance,
    edges: tuple[tuple[int, int], ...],
    *,
    radius_px: int,
    faint: bool,
) -> None:
    edge_color = np.asarray(_edge_rgb(instance.color_rgb), dtype=np.uint8)
    if faint:
        edge_color = np.asarray(np.clip(np.rint((edge_color.astype(np.float32) * 0.45) + 132.0), 0, 255), dtype=np.uint8)
    for start, end in edges:
        _draw_flat_segment(
            image=image,
            start=instance.screen_points[start],
            end=instance.screen_points[end],
            color=edge_color,
            radius_px=radius_px,
        )


def _draw_depth_tested_segment(
    *,
    image: np.ndarray,
    depth_buffer: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
    depth_start: float,
    depth_end: float,
    color: np.ndarray,
    radius_px: int,
) -> None:
    x0 = float(start[0])
    y0 = float(start[1])
    x1 = float(end[0])
    y1 = float(end[1])
    dx = x1 - x0
    dy = y1 - y0
    steps = max(1, int(math.ceil(max(abs(dx), abs(dy)))))
    offsets = _brush_offsets(radius_px)
    for step in range(steps + 1):
        t = step / steps
        xi = int(round(x0 + (dx * t)))
        yi = int(round(y0 + (dy * t)))
        depth = depth_start + ((depth_end - depth_start) * t) + 5e-4
        for ox, oy in offsets:
            px = xi + ox
            py = yi + oy
            if 0 <= px < image.shape[1] and 0 <= py < image.shape[0]:
                if depth >= (float(depth_buffer[py, px]) - 1e-3):
                    image[py, px] = color


def _brush_offsets(radius_px: int) -> tuple[tuple[int, int], ...]:
    offsets: list[tuple[int, int]] = []
    radius_squared = radius_px * radius_px
    for dy in range(-radius_px, radius_px + 1):
        for dx in range(-radius_px, radius_px + 1):
            if (dx * dx) + (dy * dy) <= radius_squared:
                offsets.append((dx, dy))
    return tuple(offsets)


def _draw_axes_overlay(
    image: np.ndarray,
    *,
    right: np.ndarray,
    true_up: np.ndarray,
    background_rgb: np.ndarray,
) -> None:
    box_size = min(AXIS_BOX_SIZE_PX, max(24, min(image.shape[0], image.shape[1]) // 4))
    placement = _best_axis_corner(image, background_rgb, box_size=box_size)
    if placement is None:
        return
    x0, y0 = placement
    x1 = min(x0 + box_size, image.shape[1])
    y1 = min(y0 + box_size, image.shape[0])
    image[y0:y1, x0:x1] = background_rgb
    origin = np.asarray((x0 + 10.0, y1 - 10.0), dtype=np.float64)
    axis_length = float(min(x1 - x0, y1 - y0) - 18)
    if axis_length <= 6.0:
        return
    basis_by_axis = (
        (np.asarray((1.0, 0.0, 0.0)), np.asarray((214, 71, 71), dtype=np.uint8)),
        (np.asarray((0.0, 1.0, 0.0)), np.asarray((62, 165, 83), dtype=np.uint8)),
        (np.asarray((0.0, 0.0, 1.0)), np.asarray((65, 111, 219), dtype=np.uint8)),
    )
    for world_axis, color in basis_by_axis:
        projected = np.asarray((float(np.dot(world_axis, right)), -float(np.dot(world_axis, true_up))))
        magnitude = float(np.linalg.norm(projected))
        if magnitude <= 1e-9:
            continue
        end = origin + ((projected / magnitude) * axis_length)
        _draw_flat_segment(
            image=image,
            start=origin,
            end=end,
            color=color,
            radius_px=1,
        )


def _best_axis_corner(image: np.ndarray, background_rgb: np.ndarray, *, box_size: int) -> tuple[int, int] | None:
    corners = (
        (0, image.shape[0] - box_size),
        (image.shape[1] - box_size, image.shape[0] - box_size),
        (0, 0),
        (image.shape[1] - box_size, 0),
    )
    best_corner: tuple[int, int] | None = None
    best_score = -1
    for x0, y0 in corners:
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(x0 + box_size, image.shape[1])
        y1 = min(y0 + box_size, image.shape[0])
        if x0 >= x1 or y0 >= y1:
            continue
        patch = image[y0:y1, x0:x1]
        background_count = int(np.count_nonzero(np.all(patch == background_rgb, axis=2)))
        if background_count > best_score:
            best_score = background_count
            best_corner = (x0, y0)
    return best_corner


def _draw_flat_segment(
    *,
    image: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
    color: np.ndarray,
    radius_px: int,
) -> None:
    x0 = float(start[0])
    y0 = float(start[1])
    x1 = float(end[0])
    y1 = float(end[1])
    dx = x1 - x0
    dy = y1 - y0
    steps = max(1, int(math.ceil(max(abs(dx), abs(dy)))))
    offsets = _brush_offsets(radius_px)
    for step in range(steps + 1):
        t = step / steps
        xi = int(round(x0 + (dx * t)))
        yi = int(round(y0 + (dy * t)))
        for ox, oy in offsets:
            px = xi + ox
            py = yi + oy
            if 0 <= px < image.shape[1] and 0 <= py < image.shape[0]:
                image[py, px] = color


def _crop_to_content(image: np.ndarray, background_rgb: np.ndarray) -> np.ndarray:
    content_mask = np.any(image != background_rgb, axis=2)
    if not np.any(content_mask):
        return image
    ys, xs = np.where(content_mask)
    min_x = max(int(xs.min()) - CROP_PADDING_PX, 0)
    max_x = min(int(xs.max()) + CROP_PADDING_PX + 1, image.shape[1])
    min_y = max(int(ys.min()) - CROP_PADDING_PX, 0)
    max_y = min(int(ys.max()) + CROP_PADDING_PX + 1, image.shape[0])
    return image[min_y:max_y, min_x:max_x].copy()


def _edge_rgb(color_rgb: tuple[float, float, float]) -> tuple[int, int, int]:
    base = np.asarray(_rgb_u8(color_rgb), dtype=np.float32)
    darkened = np.clip(np.rint((base * 0.38) - 6.0), 0, 255).astype(np.uint8)
    return (int(darkened[0]), int(darkened[1]), int(darkened[2]))


def _rgb_u8(rgb: tuple[float, float, float]) -> tuple[int, int, int]:
    return tuple(int(round(max(0.0, min(1.0, float(channel))) * 255.0)) for channel in rgb)


def _transparent_background(image: np.ndarray, background_color: tuple[float, float, float]) -> np.ndarray:
    background_rgb = np.asarray(_rgb_u8(background_color), dtype=np.uint8)
    alpha = np.where(np.all(image == background_rgb, axis=2), 0, 255).astype(np.uint8)
    return np.dstack((image, alpha))


def _write_png(image: np.ndarray, png_path: Path) -> None:
    if image.ndim != 3 or image.shape[2] not in {3, 4}:
        raise ValueError("PNG image must be an HxWx3 RGB or HxWx4 RGBA array")
    png_path.parent.mkdir(parents=True, exist_ok=True)

    height, width, channels = image.shape
    scanlines = bytearray()
    for row in image:
        scanlines.append(0)
        scanlines.extend(row.astype(np.uint8, copy=False).tobytes())

    def chunk(tag: bytes, data: bytes) -> bytes:
        payload = tag + data
        return (
            len(data).to_bytes(4, "big")
            + payload
            + zlib.crc32(payload).to_bytes(4, "big")
        )

    png_bytes = bytearray(b"\x89PNG\r\n\x1a\n")
    png_bytes.extend(
        chunk(
            b"IHDR",
            width.to_bytes(4, "big")
            + height.to_bytes(4, "big")
            + bytes((8, 6 if channels == 4 else 2, 0, 0, 0)),
        )
    )
    png_bytes.extend(chunk(b"IDAT", zlib.compress(bytes(scanlines), level=9)))
    png_bytes.extend(chunk(b"IEND", b""))
    png_path.write_bytes(png_bytes)


if __name__ == "__main__":
    raise SystemExit(main())
