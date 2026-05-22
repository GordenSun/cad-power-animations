#!/usr/bin/env python3
"""Download SendCutSend source files with a 24-hour local cache."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SOURCES = {
    "ordering_guide": {
        "filename": "sendcutsend-ordering-guide.md",
        "url": "https://cdn.sendcutsend.com/specs/sendcutsend-ordering-guide.md",
        "kind": "markdown",
        "role": "Ordering flow, accepted formats, and plain-language design rules.",
    },
    "catalog": {
        "filename": "sendcutsend-catalog.json",
        "url": "https://cdn.sendcutsend.com/specs/sendcutsend-catalog.json",
        "kind": "json",
        "role": "Orderability facts: materials, SKUs, services, stock, hardware, finishes.",
    },
    "specs": {
        "filename": "sendcutsend-specs.json",
        "url": "https://cdn.sendcutsend.com/specs/sendcutsend-specs.json",
        "kind": "json",
        "role": "Engineering facts: tolerances, holes, bridges, bending, and service specs.",
    },
}

MANIFEST_NAME = "sources-manifest.json"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def default_output_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / "generated"


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def fetch_url(url: str, timeout: float) -> tuple[bytes, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": "sendcutsend-skill-source-downloader"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        headers = {key.lower(): value for key, value in response.headers.items()}
        return response.read(), headers


def json_metadata(data: bytes, kind: str) -> dict[str, Any]:
    if kind != "json":
        return {}
    try:
        decoded = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"parse_error": "Downloaded JSON source could not be parsed."}
    meta = decoded.get("_meta") if isinstance(decoded, dict) else None
    return meta if isinstance(meta, dict) else {}


def is_cache_fresh(entry: dict[str, Any], dest: Path, now: datetime, max_age_hours: float) -> bool:
    if not dest.exists():
        return False
    fetched_at = parse_datetime(entry.get("fetched_at"))
    if fetched_at is None:
        return False
    return now - fetched_at < timedelta(hours=max_age_hours)


def cache_expires_at(entry: dict[str, Any], max_age_hours: float) -> str | None:
    fetched_at = parse_datetime(entry.get("fetched_at"))
    if fetched_at is None:
        return None
    return isoformat(fetched_at + timedelta(hours=max_age_hours))


def build_manifest(base: dict[str, Any], output_dir: Path, max_age_hours: float, now: datetime) -> dict[str, Any]:
    sources = base.get("sources") if isinstance(base.get("sources"), dict) else {}
    return {
        "generated_at": isoformat(now),
        "cache": {
            "directory": str(output_dir),
            "max_age_hours": max_age_hours,
            "policy": "Use cached source files while younger than max_age_hours; use --skip-cache to refetch now.",
        },
        "sources": dict(sources),
    }


def download_sources(
    output_dir: Path,
    *,
    skip_cache: bool = False,
    max_age_hours: float = 24,
    timeout: float = 30,
    now: datetime | None = None,
    sources: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    now = now or utc_now()
    selected_sources = sources or SOURCES
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = output_dir / MANIFEST_NAME
    manifest = build_manifest(load_manifest(manifest_path), output_dir, max_age_hours, now)
    results: list[dict[str, Any]] = []

    for key, source in selected_sources.items():
        dest = output_dir / source["filename"]
        previous = manifest["sources"].get(key, {})

        if not skip_cache and isinstance(previous, dict) and is_cache_fresh(previous, dest, now, max_age_hours):
            cached = dict(previous)
            cached.update({
                "key": key,
                "status": "cached",
                "path": str(dest),
                "cache_expires_at": cache_expires_at(previous, max_age_hours),
            })
            manifest["sources"][key] = cached
            results.append(cached)
            continue

        entry: dict[str, Any] = {
            "key": key,
            "status": "unavailable",
            "filename": source["filename"],
            "path": str(dest),
            "url": source["url"],
            "kind": source["kind"],
            "role": source["role"],
            "fetched_at": None,
            "cache_expires_at": None,
        }

        try:
            data, headers = fetch_url(source["url"], timeout=timeout)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            entry["error"] = str(exc)
            if dest.exists() and isinstance(previous, dict):
                entry["status"] = "stale_fetch_failed"
                entry["fetched_at"] = previous.get("fetched_at")
                entry["cache_expires_at"] = cache_expires_at(previous, max_age_hours)
                entry["sha256"] = previous.get("sha256")
                entry["bytes"] = previous.get("bytes")
            manifest["sources"][key] = entry
            results.append(entry)
            continue

        write_atomic(dest, data)
        fetched_at = isoformat(now)
        entry.update({
            "status": "fetched",
            "fetched_at": fetched_at,
            "cache_expires_at": isoformat(now + timedelta(hours=max_age_hours)),
            "sha256": sha256_bytes(data),
            "bytes": len(data),
            "etag": headers.get("etag"),
            "last_modified": headers.get("last-modified"),
            "json_meta": json_metadata(data, source["kind"]),
        })
        manifest["sources"][key] = entry
        results.append(entry)

    write_json(manifest_path, manifest)
    return {
        "ok": all(item["status"] in {"cached", "fetched"} for item in results),
        "output_dir": str(output_dir),
        "manifest": str(manifest_path),
        "skip_cache": skip_cache,
        "max_age_hours": max_age_hours,
        "results": results,
    }


def render_text(summary: dict[str, Any]) -> str:
    lines = [
        f"Output: {summary['output_dir']}",
        f"Manifest: {summary['manifest']}",
        f"Cache: max age {summary['max_age_hours']} hours; skip_cache={summary['skip_cache']}",
        "Sources:",
    ]
    for item in summary["results"]:
        extra = ""
        if item.get("cache_expires_at"):
            extra = f"; cache_expires_at={item['cache_expires_at']}"
        if item.get("error"):
            extra += f"; error={item['error']}"
        lines.append(f"- {item['filename']}: {item['status']}{extra}")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=default_output_dir(), help="Directory for downloaded source files.")
    parser.add_argument("--skip-cache", action="store_true", help="Ignore fresh cached files and refetch all sources now.")
    parser.add_argument("--max-age-hours", type=float, default=24, help="Cache freshness window in hours.")
    parser.add_argument("--timeout", type=float, default=30, help="Network timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    summary = download_sources(
        args.output_dir,
        skip_cache=args.skip_cache,
        max_age_hours=args.max_age_hours,
        timeout=args.timeout,
    )
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(render_text(summary))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
