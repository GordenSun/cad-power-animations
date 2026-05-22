from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from common.assembly_spec import REPO_ROOT, find_step_path, resolve_cad_source_path
from common.cad_ref_syntax import normalize_cad_path, parse_cad_tokens
from common.glb_topology import read_step_topology_bundle_from_glb, read_step_topology_manifest_from_glb
from common.render import existing_part_glb_path, part_glb_path, sha256_file
from common.selector_types import SelectorBundle


STEP_SUFFIXES = (".step", ".stp")
REGENERATE_STEP_COMMAND = "python scripts/step"
REGENERATE_STEP_PROMPT = "Regenerate STEP artifacts with the following command using the CAD skill:"


class CadRefError(RuntimeError):
    pass


@dataclass(frozen=True)
class EntryTarget:
    cad_path: str
    selectors: tuple[str, ...] = ()

    @property
    def token(self) -> str:
        from common.cad_ref_syntax import build_cad_token

        if not self.selectors:
            return build_cad_token(self.cad_path)
        return build_cad_token(self.cad_path, ",".join(self.selectors))


@dataclass(frozen=True)
class ResolvedStepTarget:
    cad_path: str
    kind: str
    source_path: Path
    step_path: Path


@dataclass(frozen=True)
class StepTopologyArtifact:
    cad_path: str
    kind: str
    source_path: Path
    step_path: Path
    glb_path: Path
    manifest: dict[str, object]
    selector_bundle: SelectorBundle | None = None


class StepTopologyArtifactError(CadRefError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        cad_path: str,
        step_path: Path,
        glb_path: Path,
        regenerate_command: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.cad_path = cad_path
        self.step_path = step_path
        self.glb_path = glb_path
        self.regenerate_command = regenerate_command

    def to_error(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": str(self),
            "cadPath": self.cad_path,
            "stepPath": _relative_to_repo(self.step_path),
            "glbPath": _relative_to_repo(self.glb_path),
            "regenerateCommand": self.regenerate_command,
        }


def cad_ref_error_payload(exc: CadRefError) -> dict[str, object]:
    if isinstance(exc, StepTopologyArtifactError):
        return exc.to_error()
    return {"message": str(exc)}


def cad_path_from_target(target: str) -> str:
    return entry_target_from_target(target).cad_path


def entry_target_from_target(target: str) -> EntryTarget:
    parsed_tokens = parse_cad_tokens(target)
    if parsed_tokens:
        if len(parsed_tokens) != 1:
            raise CadRefError("Expected exactly one @cad[...] token.")
        parsed = parsed_tokens[0]
        return EntryTarget(parsed.cad_path, parsed.selectors)
    raw_target = str(target or "").strip()
    if _raw_step_path(raw_target) is not None:
        normalized = normalize_cad_path(raw_target)
        if normalized is not None:
            return EntryTarget(normalized)
    normalized = normalize_cad_path(target)
    if normalized is None:
        raise CadRefError(f"Invalid CAD entry target: {target}")
    return EntryTarget(normalized)


def step_path_from_target(target: str) -> Path:
    raw_step_path = _raw_step_path(str(target or "").strip())
    if raw_step_path is not None:
        return raw_step_path

    entry_target = entry_target_from_target(target)
    direct_step_path = _direct_step_path(entry_target.cad_path)
    if direct_step_path is not None:
        return direct_step_path

    lookup_cad_path = _lookup_cad_path(entry_target.cad_path)
    step_path = find_step_path(lookup_cad_path)
    if step_path is None:
        raise CadRefError(f"STEP file not found for target '{target}'.")
    return step_path


def resolve_step_target(target: str) -> ResolvedStepTarget:
    entry_target = entry_target_from_target(target)
    cad_path = entry_target.cad_path
    raw_step_path = _raw_step_path(str(target or "").strip())
    if raw_step_path is not None:
        lookup_cad_path = _lookup_cad_path(cad_path)
        resolved = resolve_cad_source_path(lookup_cad_path)
        resolved_step_path = find_step_path(lookup_cad_path) if resolved is not None else None
        if resolved is not None and resolved_step_path is not None and resolved_step_path.resolve() == raw_step_path.resolve():
            kind, source_path = resolved
            return ResolvedStepTarget(
                cad_path=cad_path,
                kind=kind,
                source_path=source_path,
                step_path=raw_step_path,
            )
        return ResolvedStepTarget(
            cad_path=cad_path,
            kind="part",
            source_path=raw_step_path,
            step_path=raw_step_path,
        )

    direct_step_path = _direct_step_path(cad_path)
    if direct_step_path is not None:
        return ResolvedStepTarget(
            cad_path=cad_path,
            kind="part",
            source_path=direct_step_path,
            step_path=direct_step_path,
        )

    lookup_cad_path = _lookup_cad_path(cad_path)
    resolved = resolve_cad_source_path(lookup_cad_path)
    if resolved is None:
        raise CadRefError(f"CAD STEP ref not found for '{cad_path}'.")
    kind, source_path = resolved
    if kind in {"part", "assembly"}:
        step_path = find_step_path(lookup_cad_path)
        if step_path is None:
            raise CadRefError(f"STEP file not found for ref '{cad_path}'.")
        return ResolvedStepTarget(
            cad_path=cad_path,
            kind=kind,
            source_path=source_path,
            step_path=step_path,
        )

    raise CadRefError(f"CAD ref '{cad_path}' is not STEP-backed.")


def validate_step_topology_artifact(
    target: ResolvedStepTarget,
    *,
    glb_path: Path | None = None,
    require_selector: bool = False,
) -> StepTopologyArtifact:
    resolved_glb_path = glb_path or existing_part_glb_path(target.step_path) or part_glb_path(target.step_path)
    if not resolved_glb_path.is_file():
        raise _topology_artifact_error(
            code="missing_glb",
            reason="STEP topology validation requires the generated GLB artifact, but it is missing",
            cad_path=target.cad_path,
            kind=target.kind,
            source_path=target.source_path,
            step_path=target.step_path,
            glb_path=resolved_glb_path,
        )

    manifest = read_step_topology_manifest_from_glb(resolved_glb_path)
    if manifest is None:
        raise _topology_artifact_error(
            code="missing_step_topology",
            reason="STEP topology validation requires readable STEP_topology indexView in the GLB",
            cad_path=target.cad_path,
            kind=target.kind,
            source_path=target.source_path,
            step_path=target.step_path,
            glb_path=resolved_glb_path,
        )
    try:
        schema_version = int(manifest.get("schemaVersion") or 0)
    except (TypeError, ValueError):
        schema_version = 0
    if schema_version != 1:
        raise _topology_artifact_error(
            code="unsupported_step_topology",
            reason="STEP topology validation requires STEP_topology schemaVersion 1 in the GLB",
            cad_path=target.cad_path,
            kind=target.kind,
            source_path=target.source_path,
            step_path=target.step_path,
            glb_path=resolved_glb_path,
        )
    step_hash = str(manifest.get("stepHash") or "").strip()
    if not step_hash or step_hash != sha256_file(target.step_path):
        raise _topology_artifact_error(
            code="stale_step_topology",
            reason="GLB STEP_topology is stale for the current STEP file",
            cad_path=target.cad_path,
            kind=target.kind,
            source_path=target.source_path,
            step_path=target.step_path,
            glb_path=resolved_glb_path,
        )

    selector_bundle = None
    if require_selector:
        selector_bundle = read_step_topology_bundle_from_glb(resolved_glb_path)
        if selector_bundle is None:
            raise _topology_artifact_error(
                code="missing_selector_topology",
                reason="STEP topology validation requires readable STEP_topology selectorView in the GLB",
                cad_path=target.cad_path,
                kind=target.kind,
                source_path=target.source_path,
                step_path=target.step_path,
                glb_path=resolved_glb_path,
            )

    return StepTopologyArtifact(
        cad_path=target.cad_path,
        kind=target.kind,
        source_path=target.source_path,
        step_path=target.step_path,
        glb_path=resolved_glb_path,
        manifest=manifest,
        selector_bundle=selector_bundle,
    )


def _direct_step_path(cad_path: str) -> Path | None:
    for suffix in STEP_SUFFIXES:
        candidate = (REPO_ROOT / f"{cad_path}{suffix}").resolve()
        if candidate.is_file():
            return candidate
    return None


def _raw_step_path(target: str) -> Path | None:
    if not target:
        return None
    path = Path(target).expanduser()
    if path.suffix.lower() not in STEP_SUFFIXES:
        return None
    resolved = path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()
    return resolved if resolved.is_file() else None


def _topology_artifact_error(
    *,
    code: str,
    reason: str,
    cad_path: str,
    kind: str,
    source_path: Path,
    step_path: Path,
    glb_path: Path,
) -> StepTopologyArtifactError:
    return StepTopologyArtifactError(
        code=code,
        cad_path=cad_path,
        step_path=step_path,
        glb_path=glb_path,
        regenerate_command=REGENERATE_STEP_COMMAND,
        message=(
            f"{reason}: {_relative_to_repo(glb_path)}.\n"
            f"{REGENERATE_STEP_PROMPT}"
        ),
    )


def _cad_path_lookup_candidates(cad_path: str) -> tuple[str, ...]:
    return (cad_path,) if cad_path else ()


def _lookup_cad_path(cad_path: str) -> str:
    for candidate in _cad_path_lookup_candidates(cad_path):
        if resolve_cad_source_path(candidate) is not None:
            return candidate
    return cad_path


def _relative_to_repo(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()
