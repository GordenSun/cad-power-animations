import base64
import contextlib
import hashlib
import io
import json
import argparse
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
import zlib
from array import array
from pathlib import Path
from unittest import mock

import numpy as np

RENDER_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = RENDER_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from common.glb import _GlbBuilder
from common.render import part_glb_path
from common.step_scene import SelectorBundle
from render import cli as render_cli
from step import cli as step_cli
from common.tests.cad_test_roots import IsolatedCadRoots


def _png_data_url(path: Path) -> str:
    image = np.asarray(
        [
            [(18, 42, 96), (84, 120, 190)],
            [(140, 176, 220), (240, 244, 248)],
        ],
        dtype=np.uint8,
    )
    render_cli._write_png(image, path)
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _gif_info(path: Path) -> dict[str, object]:
    from PIL import Image, ImageSequence

    with Image.open(path) as image:
        durations = [int(frame.info.get("duration", 0)) for frame in ImageSequence.Iterator(image)]
        return {
            "frames": len(durations),
            "loop": image.info.get("loop"),
            "durations": durations,
        }


def _post_json(url: str, payload: dict[str, object]) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        response.read()


def _origin(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


class _FakePage:
    def __init__(self, result_payload: dict[str, object] | None) -> None:
        self.result_payload = result_payload
        self.goto_urls: list[str] = []

    def goto(self, url: str, **_kwargs: object) -> None:
        self.goto_urls.append(url)
        if self.result_payload is not None:
            _post_json(f"{_origin(url)}/result", self.result_payload)


class _FakeBrowserContext:
    def __init__(self, page: _FakePage) -> None:
        self.page = page
        self.closed = False

    def new_page(self) -> _FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, page: _FakePage) -> None:
        self.page = page
        self.closed = False
        self.context: _FakeBrowserContext | None = None

    def new_context(self, **_kwargs: object) -> _FakeBrowserContext:
        self.context = _FakeBrowserContext(self.page)
        return self.context

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.browser = browser

    def launch(self, **_kwargs: object) -> _FakeBrowser:
        return self.browser


class _FakePlaywright:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.chromium = _FakeChromium(browser)


class _FakePlaywrightManager:
    def __init__(self, page: _FakePage) -> None:
        self.browser = _FakeBrowser(page)
        self.playwright = _FakePlaywright(self.browser)
        self.exited = False

    def __enter__(self) -> _FakePlaywright:
        return self.playwright

    def __exit__(self, *_exc: object) -> None:
        self.exited = True


class _FakeDaemonWorker:
    instances: list["_FakeDaemonWorker"] = []

    def __init__(self) -> None:
        self.started = True
        self.closed = False
        self.jobs: list[dict[str, object]] = []
        self.__class__.instances.append(self)

    def render(self, job: dict[str, object]) -> dict[str, object]:
        self.jobs.append(job)
        if job.get("fail"):
            raise RuntimeError("fake daemon render failed")
        return {"ok": True, "outputs": [], "timings": {"fakeJobCount": len(self.jobs)}}

    def close(self) -> None:
        self.closed = True
        self.started = False


def _wait_for_socket(socket_path: Path) -> None:
    deadline = time.monotonic() + 2.0
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if socket_path.exists():
            try:
                response = render_cli._send_render_daemon_request(
                    socket_path,
                    {"command": "status"},
                    timeout_seconds=0.1,
                )
            except Exception as exc:
                last_error = exc
            else:
                if response.get("ok"):
                    return
        time.sleep(0.01)
    message = f"socket did not become ready: {socket_path}"
    if last_error is not None:
        message += f" ({last_error})"
    raise AssertionError(message)


def _short_socket_path(label: str) -> Path:
    digest = hashlib.sha256(f"{label}-{time.monotonic_ns()}".encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"cad-render-test-{digest}.sock"


def _read_png_rgb(path: Path) -> np.ndarray:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("invalid PNG signature")
    cursor = 8
    width = 0
    height = 0
    color_type = 2
    idat = bytearray()
    while cursor < len(data):
        length = int.from_bytes(data[cursor : cursor + 4], "big")
        chunk_type = data[cursor + 4 : cursor + 8]
        chunk_data = data[cursor + 8 : cursor + 8 + length]
        cursor += 12 + length
        if chunk_type == b"IHDR":
            width = int.from_bytes(chunk_data[0:4], "big")
            height = int.from_bytes(chunk_data[4:8], "big")
            color_type = int(chunk_data[9])
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break
    channels = 4 if color_type == 6 else 3
    raw = zlib.decompress(bytes(idat))
    rows = []
    stride = (width * channels) + 1
    previous = bytearray(width * channels)
    for row_index in range(height):
        row = raw[row_index * stride : (row_index + 1) * stride]
        rows.append(
            np.frombuffer(
                _unfilter_png_row(row[0], row[1:], previous, channels),
                dtype=np.uint8,
            ).reshape(width, channels)
        )
        previous = bytearray(rows[-1].reshape(-1).tolist())
    return np.stack(rows, axis=0)


def _unfilter_png_row(filter_type: int, row: bytes, previous: bytearray, bytes_per_pixel: int) -> bytes:
    output = bytearray(row)
    if filter_type == 0:
        return bytes(output)
    for index, value in enumerate(row):
        left = output[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        up = previous[index]
        upper_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        if filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        elif filter_type == 4:
            predictor = _png_paeth(left, up, upper_left)
        else:
            raise AssertionError(f"unsupported PNG filter in test helper: {filter_type}")
        output[index] = (value + predictor) & 0xFF
    return bytes(output)


def _png_paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= upper_left_distance:
        return left
    if up_distance <= upper_left_distance:
        return up
    return upper_left


def _write_visual_only_box_glb(glb_path: Path) -> Path:
    builder = _box_glb_builder(name="box")
    return builder.write(glb_path)


def _write_box_glb_with_topology(step_path: Path, *, name: str = "box") -> Path:
    glb_path = part_glb_path(step_path)
    builder = _box_glb_builder(name=name)
    manifest = {
        "schemaVersion": 1,
        "profile": "artifact",
        "stepPath": step_path.as_posix(),
        "stepHash": hashlib.sha256(step_path.read_bytes()).hexdigest(),
        "bbox": {"min": [-10, -7.5, -5], "max": [10, 7.5, 5]},
        "stats": {"occurrenceCount": 1, "leafOccurrenceCount": 1},
        "tables": {"occurrenceColumns": ["id", "name", "sourcePath"]},
        "occurrences": [{"id": "o1", "occurrenceId": "o1", "name": name, "sourcePath": step_path.as_posix()}],
        "assembly": {
            "mesh": {
                "url": f".{step_path.name}.glb",
                "addressing": "gltf-node-extras",
                "occurrenceIdKey": "cadOccurrenceId",
            },
            "root": {
                "id": "o1",
                "occurrenceId": "o1",
                "nodeType": "part",
                "displayName": name,
                "sourcePath": step_path.as_posix(),
                "bbox": {"min": [-10, -7.5, -5], "max": [10, 7.5, 5]},
            },
        },
        "shapes": [],
        "faces": [],
        "edges": [],
        "vertices": [],
    }
    builder.add_step_topology(
        SelectorBundle(
            manifest=manifest,
            buffers={"edgeIds": array("I", [1, 2, 3])},
        ),
        entry_kind="part",
    )
    return builder.write(glb_path)


def _box_glb_builder(*, name: str) -> _GlbBuilder:
    builder = _GlbBuilder()
    material = builder.add_material((0.65, 0.72, 0.82, 1.0))
    x, y, z = 0.010, 0.0075, 0.005
    vertices = [
        (-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z),
        (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z),
    ]
    triangles = [
        (0, 2, 1), (0, 3, 2),
        (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4),
        (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6),
        (3, 0, 4), (3, 4, 7),
    ]
    positions = array("f", [coordinate for vertex in vertices for coordinate in vertex])
    normals = array("f", [0.0 for _ in vertices for _coordinate in range(3)])
    indices = array("I", [index for triangle in triangles for index in triangle])
    mesh = builder.add_mesh(
        positions,
        normals,
        [(indices, material)],
        minimum=[-x, -y, -z],
        maximum=[x, y, z],
        name=name,
    )
    assert mesh is not None
    node = builder.add_node(
        {
            "name": "o1",
            "mesh": mesh,
            "extras": {
                "cadOccurrenceId": "o1",
                "cadName": name,
            },
        }
    )
    builder.set_scene_nodes([node])
    return builder


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._isolated_roots = IsolatedCadRoots(self, prefix="render-")
        tempdir = self._isolated_roots.temporary_cad_directory(prefix="tmp-render-")
        self._tempdir = tempdir
        self.temp_root = Path(tempdir.name)
        self.browser_jobs: list[dict[str, object]] = []
        self._real_browser_renderer = render_cli._run_browser_render_job
        self._browser_patch = mock.patch.object(
            render_cli,
            "_run_browser_render_job",
            side_effect=self._fake_browser_renderer,
        )
        self._browser_patch.start()
        self.addCleanup(self._browser_patch.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root, ignore_errors=True)
        self._tempdir.cleanup()

    def _write_box_step(self, name: str = "box") -> Path:
        step_path = self.temp_root / f"{name}.step"
        step_path.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n")
        _write_box_glb_with_topology(step_path, name=name)
        return step_path

    def test_render_camera_presets_are_z_up(self) -> None:
        self.assertEqual((0.0, 0.0, 1.0), render_cli.resolve_view("front").up)
        self.assertEqual((0.0, 0.0, 1.0), render_cli.resolve_view("iso").up)
        self.assertEqual((0.0, 0.0, 1.0), render_cli.resolve_view("45:30").up)
        self.assertEqual((0.0, 0.0, 1.0), render_cli.resolve_view("top").direction)

    def _fake_browser_renderer(self, job: dict[str, object]) -> dict[str, object]:
        self.browser_jobs.append(json.loads(json.dumps(job)))
        width = int(job["width"])
        height = int(job["height"])
        transparent = bool(job.get("transparent"))
        background = tuple(float(value) for value in job.get("background", [1, 1, 1]))
        background_rgb = np.asarray(render_cli._rgb_u8(background), dtype=np.uint8)
        if transparent:
            image = np.zeros((height, width, 4), dtype=np.uint8)
            image[:, :, :3] = background_rgb
        else:
            image = np.empty((height, width, 3), dtype=np.uint8)
            image[:, :, :] = background_rgb
        y0, y1 = max(0, height // 4), min(height, (height * 3) // 4)
        x0, x1 = max(0, width // 4), min(width, (width * 3) // 4)
        outputs: list[dict[str, object]] = []
        for index, output in enumerate(job.get("outputs", [])):
            frame_image = image.copy()
            color = np.asarray(
                (
                    (38 + index * 29) % 256,
                    (92 + index * 17) % 256,
                    (168 + index * 11) % 256,
                ),
                dtype=np.uint8,
            )
            frame_image[y0:y1, x0:x1, :3] = color
            if transparent:
                frame_image[y0:y1, x0:x1, 3] = 255
            output_path = Path(str(output["path"]))
            render_cli._write_png(frame_image, output_path)
            outputs.append(
                {
                    "camera": str(output.get("camera", "iso")),
                    "path": output_path.resolve().as_posix(),
                    "width": width,
                    "height": height,
                }
            )
        return {"ok": True, "outputs": outputs, "timings": {"loadCount": 1, "renderMs": 0}}

    def test_render_view_renders_step(self) -> None:
        step_path = self._write_box_step()
        png_path = self.temp_root / "box.png"

        render_cli.main(
            [
                "view",
                str(step_path),
                "--output",
                str(png_path),
                "--width",
                "240",
                "--height",
                "160",
                "--no-axes",
            ]
        )

        pixels = _read_png_rgb(png_path)
        self.assertLessEqual(pixels.shape[0], 160)
        self.assertLessEqual(pixels.shape[1], 240)
        self.assertGreater(len(np.unique(pixels[:, :, :3].reshape(-1, 3), axis=0)), 1)

    def test_render_rejects_visual_only_glb_inputs(self) -> None:
        mesh_path = self.temp_root / "mesh.glb"
        _write_visual_only_box_glb(mesh_path)

        with self.assertRaisesRegex(render_cli.CadRefError, "does not include readable STEP_topology"):
            render_cli.main(["view", str(mesh_path), "--output", str(self.temp_root / "mesh.png")])

    def test_render_rejects_stale_step_topology(self) -> None:
        step_path = self._write_box_step()
        step_path.write_text("ISO-10303-21;\n/* changed */\nEND-ISO-10303-21;\n")

        with self.assertRaises(render_cli.CadRefError) as context:
            render_cli.render_json_result(["list", str(step_path)])
        message = str(context.exception)
        self.assertIn("stale", message)
        self.assertIn("\nRegenerate STEP artifacts with the following command using the CAD skill:", message)
        self.assertNotIn("scripts.step", message)

    def test_render_accepts_direct_valid_glb_input(self) -> None:
        step_path = self._write_box_step()
        result = render_cli.render_json_result(["list", str(part_glb_path(step_path))])

        self.assertTrue(result["ok"])
        self.assertEqual(1, len(result["parts"]))

    def test_render_quality_flag_sets_browser_supersampling(self) -> None:
        step_path = self._write_box_step()
        png_path = self.temp_root / "box-quality.png"

        render_cli.main(
            [
                "view",
                str(step_path),
                "--quality",
                "draft",
                "--output",
                str(png_path),
            ]
        )

        self.assertTrue(png_path.exists())
        self.assertEqual("draft", self.browser_jobs[-1]["quality"])
        self.assertEqual(1.0, self.browser_jobs[-1]["renderScale"])

    def test_render_orbit_outputs_looping_gif(self) -> None:
        step_path = self._write_box_step()
        gif_path = self.temp_root / "box-orbit.gif"

        render_cli.main(
            [
                "orbit",
                str(step_path),
                "--output",
                str(gif_path),
                "--frames",
                "6",
                "--fps",
                "10",
                "--width",
                "96",
                "--height",
                "64",
                "--no-axes",
            ]
        )

        info = _gif_info(gif_path)
        self.assertEqual(6, info["frames"])
        self.assertEqual(0, info["loop"])
        self.assertEqual(1, len(self.browser_jobs))
        self.assertTrue(self.browser_jobs[-1]["lockFraming"])
        self.assertEqual(6, len(self.browser_jobs[-1]["outputs"]))
        self.assertNotEqual(
            self.browser_jobs[-1]["outputs"][0]["camera"],
            self.browser_jobs[-1]["outputs"][-1]["camera"],
        )

    def test_render_orbit_very_high_profile_defaults_and_render_scale(self) -> None:
        parser = render_cli.build_parser()
        args = parser.parse_args(["orbit", "box.step", "--output", "box.gif", "--quality", "very-high"])
        settings = render_cli._resolve_orbit_settings(args, args.render_parser)
        self.assertEqual(1600, settings.width)
        self.assertEqual(1000, settings.height)
        self.assertEqual(96, settings.frame_count)

        step_path = self._write_box_step()
        gif_path = self.temp_root / "box-very-high.gif"
        result = render_cli.render_json_result(
            [
                "orbit",
                str(step_path),
                "--output",
                str(gif_path),
                "--quality",
                "very-high",
                "--frames",
                "3",
                "--width",
                "64",
                "--height",
                "48",
                "--no-axes",
            ]
        )

        self.assertEqual("very-high", result["quality"])
        self.assertEqual(3.0, self.browser_jobs[-1]["renderScale"])
        self.assertEqual(3, len(self.browser_jobs[-1]["outputs"]))

    def test_render_orbit_rejects_invalid_options(self) -> None:
        step_path = self._write_box_step()
        cases = [
            ["--output", str(self.temp_root / "bad.png")],
            ["--output", str(self.temp_root / "bad-frames.gif"), "--frames", "1"],
            ["--output", str(self.temp_root / "bad-fps.gif"), "--fps", "0"],
            ["--output", str(self.temp_root / "bad-duration.gif"), "--duration-seconds", "0"],
        ]

        for extra_args in cases:
            with self.subTest(extra_args=extra_args):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit_context:
                    render_cli.main(["orbit", str(step_path), *extra_args])
                self.assertEqual(2, exit_context.exception.code)

    def test_render_timeout_flag_sets_browser_job_timeout(self) -> None:
        step_path = self._write_box_step()
        png_path = self.temp_root / "box-timeout.png"

        render_cli.main(
            [
                "view",
                str(step_path),
                "--timeout-seconds",
                "42.5",
                "--output",
                str(png_path),
            ]
        )

        self.assertTrue(png_path.exists())
        self.assertEqual(42.5, self.browser_jobs[-1]["timeoutSeconds"])

    def test_render_uses_daemon_by_default_and_allows_debug_disable(self) -> None:
        step_path = self._write_box_step()

        render_cli.main(["view", str(step_path), "--output", str(self.temp_root / "box-daemon-default.png")])
        render_cli.main(
            [
                "view",
                str(step_path),
                "--output",
                str(self.temp_root / "box-daemon-disabled.png"),
                "--no-daemon",
            ]
        )

        self.assertTrue(self.browser_jobs[-2]["useDaemon"])
        self.assertFalse(self.browser_jobs[-1]["useDaemon"])

    def test_render_verbose_logs_timings(self) -> None:
        step_path = self._write_box_step()
        png_path = self.temp_root / "box-verbose.png"
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            render_cli.main(["view", str(step_path), "--output", str(png_path), "--verbose"])

        self.assertTrue(png_path.exists())
        self.assertIn("renderer timings:", stderr.getvalue())
        self.assertIn("view completed in", stderr.getvalue())

    def test_render_renders_multiple_cameras_to_out_dir(self) -> None:
        step_path = self._write_box_step()
        output_dir = self.temp_root / "views"

        render_cli.main(
            [
                "view",
                str(step_path),
                "--camera",
                "iso",
                "--camera",
                "top",
                "--out-dir",
                str(output_dir),
                "--width",
                "220",
                "--height",
                "160",
                "--no-axes",
            ]
        )

        for view_name in ("iso", "top"):
            pixels = _read_png_rgb(output_dir / f"box-{view_name}.png")
            self.assertGreater(len(np.unique(pixels[:, :, :3].reshape(-1, 3), axis=0)), 1)
        self.assertEqual(1, len(self.browser_jobs))
        self.assertEqual(2, len(self.browser_jobs[0]["outputs"]))
        self.assertEqual(["o1"], self.browser_jobs[0]["visibleOccurrenceIds"])

    def test_render_lists_step_occurrences_as_json(self) -> None:
        step_path = self._write_box_step()
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            render_cli.main(["list", str(step_path)])

        rows = json.loads(stdout.getvalue())
        self.assertEqual(1, len(rows))
        self.assertEqual("o1", rows[0]["id"])
        self.assertEqual("box", rows[0]["name"])

    def test_render_json_result_uses_scene_provider_for_list(self) -> None:
        step_path = self._write_box_step()
        target = render_cli._resolve_render_target(str(step_path))
        scene = render_cli.load_glb_scene_parts(target)[0].scene
        observed_paths = []

        def provider(path):
            observed_paths.append(path.resolve())
            return scene

        result = render_cli.render_json_result(["list", str(step_path)], scene_provider=provider)

        self.assertTrue(result["ok"])
        self.assertEqual("list", result["command"])
        self.assertEqual([part_glb_path(step_path).resolve()], observed_paths)
        self.assertEqual(1, len(result["parts"]))
        self.assertEqual("o1", result["parts"][0]["id"])

    def test_render_view_alias_outputs_png(self) -> None:
        step_path = self._write_box_step()
        png_path = self.temp_root / "box-view.png"

        render_cli.main(
            [
                "view",
                str(step_path),
                "--output",
                str(png_path),
                "--width",
                "200",
                "--height",
                "140",
                "--no-axes",
            ]
        )

        pixels = _read_png_rgb(png_path)
        self.assertGreater(len(np.unique(pixels[:, :, :3].reshape(-1, 3), axis=0)), 1)
        result = render_cli.render_json_result(
            ["view", str(step_path), "--output", str(self.temp_root / "box-result.png")]
        )
        self.assertEqual("browser-three", result["renderer"])

    def _playwright_job(self, output_path: Path, *, timeout_seconds: float = 2.0) -> dict[str, object]:
        step_path = self._write_box_step("playwright-box")
        return {
            "schemaVersion": 1,
            "renderer": "render-three",
            "glbPath": part_glb_path(step_path).resolve().as_posix(),
            "displayPath": step_path.as_posix(),
            "width": 160,
            "height": 120,
            "background": [0.98, 0.985, 0.99],
            "transparent": False,
            "modelColor": [0.8, 0.84, 0.9],
            "visibleOccurrenceIds": ["o1"],
            "partOrder": ["o1"],
            "outputs": [{"camera": "iso", "path": output_path.resolve().as_posix()}],
            "preset": "solid",
            "renderMode": "solid",
            "colorBy": "step",
            "edgeStyle": "thin",
            "quality": "draft",
            "renderScale": 1.0,
            "axes": False,
            "hiddenLines": "off",
            "timeoutSeconds": timeout_seconds,
            "useDaemon": False,
        }

    def _assert_server_closed(self, render_url: str) -> None:
        with self.assertRaises(Exception):
            urllib.request.urlopen(render_url, timeout=0.2).read()

    def test_playwright_renderer_closes_browser_and_server_on_success(self) -> None:
        output_path = self.temp_root / "playwright-success.png"
        payload = {
            "ok": True,
            "outputs": [
                {
                    "camera": "iso",
                    "path": output_path.resolve().as_posix(),
                    "width": 2,
                    "height": 2,
                    "dataUrl": _png_data_url(self.temp_root / "source-success.png"),
                }
            ],
            "timings": {"renderMs": 1},
        }
        page = _FakePage(payload)
        manager = _FakePlaywrightManager(page)

        with mock.patch.object(render_cli, "_sync_playwright_context", return_value=manager):
            result = self._real_browser_renderer(self._playwright_job(output_path))

        self.assertTrue(result["ok"])
        self.assertTrue(output_path.exists())
        self.assertTrue(manager.browser.closed)
        self.assertIsNotNone(manager.browser.context)
        self.assertTrue(manager.browser.context.closed)
        self.assertTrue(manager.exited)
        self._assert_server_closed(page.goto_urls[-1])

    def test_playwright_renderer_closes_browser_and_server_on_failure_result(self) -> None:
        output_path = self.temp_root / "playwright-failure.png"
        page = _FakePage({"ok": False, "error": "intentional render failure"})
        manager = _FakePlaywrightManager(page)

        with mock.patch.object(render_cli, "_sync_playwright_context", return_value=manager):
            with self.assertRaisesRegex(RuntimeError, "intentional render failure"):
                self._real_browser_renderer(self._playwright_job(output_path))

        self.assertTrue(manager.browser.closed)
        self.assertIsNotNone(manager.browser.context)
        self.assertTrue(manager.browser.context.closed)
        self.assertTrue(manager.exited)
        self._assert_server_closed(page.goto_urls[-1])

    def test_playwright_renderer_closes_browser_and_server_on_timeout(self) -> None:
        output_path = self.temp_root / "playwright-timeout.png"
        page = _FakePage(None)
        manager = _FakePlaywrightManager(page)

        with mock.patch.object(render_cli, "_sync_playwright_context", return_value=manager):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                self._real_browser_renderer(self._playwright_job(output_path, timeout_seconds=0.01))

        self.assertTrue(manager.browser.closed)
        self.assertIsNotNone(manager.browser.context)
        self.assertTrue(manager.browser.context.closed)
        self.assertTrue(manager.exited)
        self._assert_server_closed(page.goto_urls[-1])

    def test_real_playwright_renderer_outputs_png_when_chromium_is_installed(self) -> None:
        output_path = self.temp_root / "playwright-real.png"
        try:
            self._real_browser_renderer(self._playwright_job(output_path, timeout_seconds=30.0))
        except RuntimeError as exc:
            message = str(exc)
            if "Playwright" in message or "playwright install chromium" in message:
                self.skipTest(message)
            raise

        pixels = _read_png_rgb(output_path)
        self.assertGreaterEqual(pixels.shape[0], 1)
        self.assertGreaterEqual(pixels.shape[1], 1)
        self.assertGreater(len(np.unique(pixels[:, :, :3].reshape(-1, 3), axis=0)), 1)

    def test_real_playwright_renderer_outputs_orbit_gif_when_chromium_is_installed(self) -> None:
        step_path = self._write_box_step("playwright-orbit")
        gif_path = self.temp_root / "playwright-orbit.gif"
        try:
            render_cli.render_json_result(
                [
                    "orbit",
                    str(step_path),
                    "--output",
                    str(gif_path),
                    "--frames",
                    "8",
                    "--fps",
                    "8",
                    "--width",
                    "120",
                    "--height",
                    "90",
                    "--no-axes",
                    "--no-daemon",
                    "--timeout-seconds",
                    "30",
                ],
                browser_renderer=self._real_browser_renderer,
            )
        except RuntimeError as exc:
            message = str(exc)
            if "Playwright" in message or "playwright install chromium" in message:
                self.skipTest(message)
            raise

        from PIL import Image, ImageSequence

        info = _gif_info(gif_path)
        self.assertEqual(8, info["frames"])
        with Image.open(gif_path) as image:
            first_frame = np.asarray(next(ImageSequence.Iterator(image)).convert("RGB"))
        self.assertGreater(len(np.unique(first_frame.reshape(-1, 3), axis=0)), 1)

    def test_daemon_client_starts_when_socket_is_missing(self) -> None:
        socket_path = _short_socket_path("missing")
        self.addCleanup(lambda: socket_path.unlink(missing_ok=True))
        responses = [
            render_cli._RenderDaemonConnectionError("missing"),
            {
                "protocolVersion": render_cli.RENDER_DAEMON_PROTOCOL_VERSION,
                "ok": True,
                "result": {"ok": True, "outputs": [], "timings": {}},
            },
        ]

        def fake_send(*_args, **_kwargs):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        with (
            mock.patch.object(render_cli, "_render_daemon_socket_path", return_value=socket_path),
            mock.patch.object(render_cli, "_send_render_daemon_request", side_effect=fake_send) as send_mock,
            mock.patch.object(render_cli, "_start_render_daemon", return_value=object()) as start_mock,
            mock.patch.object(render_cli, "_wait_for_render_daemon") as wait_mock,
        ):
            job = self._playwright_job(self.temp_root / "daemon-start.png")
            job["useDaemon"] = True
            result = self._real_browser_renderer(job)

        self.assertEqual("started", result["timings"]["daemon"])
        self.assertEqual(2, send_mock.call_count)
        start_mock.assert_called_once_with(socket_path)
        wait_mock.assert_called_once()

    def test_daemon_client_removes_stale_socket_before_restart(self) -> None:
        socket_path = _short_socket_path("stale")
        self.addCleanup(lambda: socket_path.unlink(missing_ok=True))
        socket_path.write_text("stale")
        responses = [
            render_cli._RenderDaemonConnectionError("stale"),
            {
                "protocolVersion": render_cli.RENDER_DAEMON_PROTOCOL_VERSION,
                "ok": True,
                "result": {"ok": True, "outputs": [], "timings": {}},
            },
        ]

        def fake_send(*_args, **_kwargs):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        with (
            mock.patch.object(render_cli, "_render_daemon_socket_path", return_value=socket_path),
            mock.patch.object(render_cli, "_send_render_daemon_request", side_effect=fake_send),
            mock.patch.object(render_cli, "_start_render_daemon", return_value=object()),
            mock.patch.object(render_cli, "_wait_for_render_daemon"),
        ):
            job = self._playwright_job(self.temp_root / "daemon-stale.png")
            job["useDaemon"] = True
            self._real_browser_renderer(job)

        self.assertFalse(socket_path.exists())

    def test_daemon_client_reports_render_failures(self) -> None:
        socket_path = _short_socket_path("failure")
        self.addCleanup(lambda: socket_path.unlink(missing_ok=True))
        with (
            mock.patch.object(render_cli, "_render_daemon_socket_path", return_value=socket_path),
            mock.patch.object(
                render_cli,
                "_send_render_daemon_request",
                return_value={
                    "protocolVersion": render_cli.RENDER_DAEMON_PROTOCOL_VERSION,
                    "ok": False,
                    "error": "daemon render failed",
                },
            ),
        ):
            job = self._playwright_job(self.temp_root / "daemon-failure.png")
            job["useDaemon"] = True
            with self.assertRaisesRegex(RuntimeError, "daemon render failed"):
                self._real_browser_renderer(job)

    def test_start_render_daemon_detaches_from_parent_session(self) -> None:
        socket_path = _short_socket_path("popen")
        log_path = render_cli._render_daemon_log_path(socket_path)
        self.addCleanup(lambda: socket_path.unlink(missing_ok=True))
        self.addCleanup(lambda: log_path.unlink(missing_ok=True))
        self.addCleanup(lambda: render_cli._STARTED_RENDER_DAEMON_PROCESSES.pop(socket_path.as_posix(), None))
        process = mock.Mock()

        with mock.patch.object(render_cli.subprocess, "Popen", return_value=process) as popen:
            self.assertIs(process, render_cli._start_render_daemon(socket_path))

        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertIs(process, render_cli._STARTED_RENDER_DAEMON_PROCESSES[socket_path.as_posix()])

    def test_daemon_server_status_render_and_stop(self) -> None:
        _FakeDaemonWorker.instances = []
        socket_path = _short_socket_path("renderd")
        self.addCleanup(lambda: socket_path.unlink(missing_ok=True))
        thread = threading.Thread(
            target=render_cli._serve_render_daemon,
            kwargs={
                "socket_path": socket_path,
                "idle_timeout_seconds": 10.0,
                "max_jobs": 10,
                "worker_factory": _FakeDaemonWorker,
            },
            daemon=True,
        )
        thread.start()
        _wait_for_socket(socket_path)

        status = render_cli._send_render_daemon_request(socket_path, {"command": "status"})
        self.assertTrue(status["ok"])
        self.assertFalse(status["browserStarted"])

        render_response = render_cli._send_render_daemon_request(
            socket_path,
            {"command": "render", "job": {"ok": True}},
        )
        self.assertTrue(render_response["ok"])
        self.assertEqual(1, render_response["result"]["timings"]["fakeJobCount"])

        status = render_cli._send_render_daemon_request(socket_path, {"command": "status"})
        self.assertTrue(status["browserStarted"])
        self.assertEqual(1, status["jobs"])

        stop = render_cli._send_render_daemon_request(socket_path, {"command": "stop"})
        self.assertTrue(stop["ok"])
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())
        self.assertTrue(_FakeDaemonWorker.instances[-1].closed)

    def test_daemon_server_returns_render_failure_json(self) -> None:
        socket_path = _short_socket_path("renderd-fail")
        self.addCleanup(lambda: socket_path.unlink(missing_ok=True))
        thread = threading.Thread(
            target=render_cli._serve_render_daemon,
            kwargs={
                "socket_path": socket_path,
                "idle_timeout_seconds": 10.0,
                "max_jobs": 10,
                "worker_factory": _FakeDaemonWorker,
            },
            daemon=True,
        )
        thread.start()
        _wait_for_socket(socket_path)

        response = render_cli._send_render_daemon_request(
            socket_path,
            {"command": "render", "job": {"fail": True}},
        )
        self.assertFalse(response["ok"])
        self.assertIn("fake daemon render failed", response["error"])
        render_cli._send_render_daemon_request(socket_path, {"command": "stop"})
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())

    def test_daemon_server_exits_after_idle_timeout(self) -> None:
        socket_path = _short_socket_path("renderd-idle")
        self.addCleanup(lambda: socket_path.unlink(missing_ok=True))
        thread = threading.Thread(
            target=render_cli._serve_render_daemon,
            kwargs={
                "socket_path": socket_path,
                "idle_timeout_seconds": 0.05,
                "max_jobs": 10,
                "worker_factory": _FakeDaemonWorker,
            },
            daemon=True,
        )
        thread.start()
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())
        self.assertFalse(socket_path.exists())

    def test_daemon_server_exits_after_max_jobs(self) -> None:
        _FakeDaemonWorker.instances = []
        socket_path = _short_socket_path("renderd-max")
        self.addCleanup(lambda: socket_path.unlink(missing_ok=True))
        thread = threading.Thread(
            target=render_cli._serve_render_daemon,
            kwargs={
                "socket_path": socket_path,
                "idle_timeout_seconds": 10.0,
                "max_jobs": 1,
                "worker_factory": _FakeDaemonWorker,
            },
            daemon=True,
        )
        thread.start()
        _wait_for_socket(socket_path)

        response = render_cli._send_render_daemon_request(
            socket_path,
            {"command": "render", "job": {"ok": True}},
        )
        self.assertTrue(response["ok"])
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())
        self.assertFalse(socket_path.exists())
        self.assertTrue(_FakeDaemonWorker.instances[-1].closed)

    def test_daemon_status_and_stop_commands(self) -> None:
        socket_path = _short_socket_path("renderd-command")
        self.addCleanup(lambda: socket_path.unlink(missing_ok=True))
        thread = threading.Thread(
            target=render_cli._serve_render_daemon,
            kwargs={
                "socket_path": socket_path,
                "idle_timeout_seconds": 10.0,
                "max_jobs": 10,
                "worker_factory": _FakeDaemonWorker,
            },
            daemon=True,
        )
        thread.start()
        _wait_for_socket(socket_path)

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            status_code = render_cli.run_daemon_command(
                argparse.Namespace(daemon_command="status", socket=socket_path)
            )
        self.assertEqual(0, status_code)
        self.assertIn("render daemon running", stdout.getvalue())

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            stop_code = render_cli.run_daemon_command(
                argparse.Namespace(daemon_command="stop", socket=socket_path)
            )
        self.assertEqual(0, stop_code)
        self.assertIn("stopped render daemon", stdout.getvalue())
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())

    def test_focus_selector_resolves_before_browser_job(self) -> None:
        step_path = self._write_box_step()
        png_path = self.temp_root / "box-focus.png"

        result = render_cli.render_json_result(
            [
                "view",
                str(step_path),
                "--focus",
                "o1",
                "--output",
                str(png_path),
            ]
        )

        self.assertTrue(result["ok"])
        self.assertEqual(["o1"], self.browser_jobs[-1]["visibleOccurrenceIds"])
        self.assertEqual(str(part_glb_path(step_path).resolve()), self.browser_jobs[-1]["glbPath"])

    def test_render_wireframe_outputs_png(self) -> None:
        step_path = self._write_box_step()
        png_path = self.temp_root / "box-wire.png"

        render_cli.main(
            [
                "wireframe",
                str(step_path),
                "--output",
                str(png_path),
                "--hidden-lines",
                "all",
                "--width",
                "240",
                "--height",
                "160",
                "--no-axes",
            ]
        )

        pixels = _read_png_rgb(png_path)
        self.assertGreater(len(np.unique(pixels[:, :, :3].reshape(-1, 3), axis=0)), 1)

    def test_render_section_outputs_svg(self) -> None:
        step_path = self._write_box_step()
        svg_path = self.temp_root / "section.svg"

        render_cli.main(
            [
                "section",
                str(step_path),
                "--plane",
                "XY",
                "--offset",
                "0",
                "--output",
                str(svg_path),
            ]
        )

        svg = svg_path.read_text()
        self.assertIn("<svg", svg)
        self.assertIn("<line", svg)
        self.assertIn('stroke="#224466"', svg)

    def test_color_policy_uses_neutral_fallback_unless_occurrence_requested(self) -> None:
        instance_without_color = render_cli.MeshInstance(
            vertices=np.empty((0, 3), dtype=np.float64),
            triangles=np.empty((0, 3), dtype=np.int64),
            color_rgb=None,
        )
        instance_with_color = render_cli.MeshInstance(
            vertices=np.empty((0, 3), dtype=np.float64),
            triangles=np.empty((0, 3), dtype=np.int64),
            color_rgb=(0.9, 0.1, 0.2),
        )
        default_color = (0.1, 0.2, 0.3)

        self.assertEqual(
            default_color,
            render_cli._color_for_policy(
                0,
                instance_without_color,
                default_color=default_color,
                count=2,
                color_by="step",
            ),
        )
        self.assertEqual(
            instance_with_color.color_rgb,
            render_cli._color_for_policy(
                0,
                instance_with_color,
                default_color=default_color,
                count=2,
                color_by="step",
            ),
        )
        self.assertEqual(
            default_color,
            render_cli._color_for_policy(
                0,
                instance_without_color,
                default_color=default_color,
                count=2,
                color_by="none",
            ),
        )
        self.assertNotEqual(
            default_color,
            render_cli._color_for_policy(
                0,
                instance_without_color,
                default_color=default_color,
                count=2,
                color_by="occurrence",
            ),
        )

        face_colored = render_cli.MeshInstance(
            vertices=np.empty((0, 3), dtype=np.float64),
            triangles=np.empty((0, 3), dtype=np.int64),
            color_rgb=(0.4, 0.5, 0.6),
            face_colors_rgb=np.asarray([[0.2, 0.3, 0.4], [np.nan, np.nan, np.nan]], dtype=np.float32),
        )
        np.testing.assert_allclose(
            render_cli._mesh_face_or_instance_color(face_colored, 0, default_color),
            (0.2, 0.3, 0.4),
        )
        self.assertEqual(default_color, render_cli._mesh_face_or_instance_color(face_colored, 1, default_color))

    def test_render_transparent_background_writes_rgba_png(self) -> None:
        step_path = self._write_box_step()
        png_path = self.temp_root / "box-transparent.png"

        render_cli.main(
            [
                "view",
                str(step_path),
                "--output",
                str(png_path),
                "--transparent",
                "--width",
                "240",
                "--height",
                "160",
                "--no-axes",
            ]
        )

        pixels = _read_png_rgb(png_path)
        self.assertEqual(4, pixels.shape[2])
        self.assertIn(0, set(int(value) for value in pixels[:, :, 3].reshape(-1)))
        self.assertIn(255, set(int(value) for value in pixels[:, :, 3].reshape(-1)))

    def test_focus_and_hide_selectors_filter_step_parts(self) -> None:
        parts = [
            render_cli.GlbScenePart(
                scene=object(),
                node_name="o1.1",
                geometry_name="box",
                transform=np.eye(4),
                part_id="o1.1",
                occurrence_id="o1.1",
                name="left_bracket",
                source_name="bracket",
                source_path="STEP/bracket.step",
                color_rgb=None,
            ),
            render_cli.GlbScenePart(
                scene=object(),
                node_name="o1.2.1",
                geometry_name="box",
                transform=np.eye(4),
                part_id="o1.2.1",
                occurrence_id="o1.2.1",
                name="imported_part",
                source_name="catalog_part",
                source_path="STEP/imports/catalog_part.step",
                color_rgb=None,
            ),
        ]

        focused = render_cli.filter_scene_parts(parts, focus="o1.2", hide=None)
        self.assertEqual(["o1.2.1"], [part.part_id for part in focused])

        hidden = render_cli.filter_scene_parts(parts, focus=None, hide="source:STEP/imports/catalog_part.step")
        self.assertEqual(["o1.1"], [part.part_id for part in hidden])

    def test_unqualified_cad_ref_selector_maps_to_single_occurrence(self) -> None:
        manifest = {
            "tables": {
                "occurrenceColumns": ["id", "path", "name", "sourceName", "parentId"],
                "faceColumns": ["id", "occurrenceId"],
            },
            "occurrences": [["o1", "1", "box", "box", None]],
            "faces": [["o1.f3", "o1"]],
        }

        self.assertEqual("o1", render_cli._occurrence_id_for_selector("f3", manifest))


class RenderDaemonIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._isolated_roots = IsolatedCadRoots(self, prefix="render-daemon-")
        tempdir = self._isolated_roots.temporary_cad_directory(prefix="tmp-render-daemon-")
        self._tempdir = tempdir
        self.temp_root = Path(tempdir.name)
        self.socket_path = _short_socket_path("real-renderd")

    def tearDown(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            render_cli.run_daemon_command(argparse.Namespace(daemon_command="stop", socket=self.socket_path))
        self.socket_path.unlink(missing_ok=True)
        render_cli._render_daemon_log_path(self.socket_path).unlink(missing_ok=True)
        shutil.rmtree(self.temp_root, ignore_errors=True)
        self._tempdir.cleanup()

    def _write_generated_box_source(self) -> Path:
        script_path = self.temp_root / "generated_daemon_box.py"
        script_path.write_text(
            "\n".join(
                [
                    "from build123d import Box",
                    "",
                    "DISPLAY_NAME = 'generated daemon box'",
                    "",
                    "def gen_step():",
                    "    return Box(12, 8, 5)",
                ]
            )
            + "\n"
        )
        return script_path

    def test_cli_renders_generated_step_twice_through_warm_daemon(self) -> None:
        source_path = self._write_generated_box_source()
        try:
            step_cli.main([str(source_path)])
        except ModuleNotFoundError as exc:
            self.skipTest(f"build123d is not installed: {exc}")

        step_path = source_path.with_suffix(".step")
        render_target = step_path.relative_to(self._isolated_roots.cad_root).with_suffix("").as_posix()
        first_png = self.temp_root / "generated-daemon-first.png"
        second_png = self.temp_root / "generated-daemon-second.png"
        render_args = [
            "view",
            render_target,
            "--width",
            "180",
            "--height",
            "120",
            "--quality",
            "draft",
            "--timeout-seconds",
            "60",
            "--no-axes",
        ]

        try:
            with mock.patch.object(render_cli, "_render_daemon_socket_path", return_value=self.socket_path):
                first = render_cli.render_json_result([*render_args, "--output", str(first_png)])
                second = render_cli.render_json_result([*render_args, "--output", str(second_png)])
        except RuntimeError as exc:
            message = str(exc)
            if "Playwright" in message or "playwright install chromium" in message or "Operation not permitted" in message:
                self.skipTest(message)
            raise

        self.assertEqual("started", first["timings"]["daemon"])
        self.assertEqual("warm", second["timings"]["daemon"])
        for png_path in (first_png, second_png):
            pixels = _read_png_rgb(png_path)
            self.assertGreaterEqual(pixels.shape[0], 1)
            self.assertGreaterEqual(pixels.shape[1], 1)
            self.assertGreater(len(np.unique(pixels[:, :, :3].reshape(-1, 3), axis=0)), 1)


if __name__ == "__main__":
    unittest.main()
