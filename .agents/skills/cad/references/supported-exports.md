# Supported exports

Read this file when the user requests STL, 3MF, or native GLB output from CAD geometry. Read `dxf.md` for DXF output, because DXF uses a separate `gen_dxf()` source contract.

## Policy

STL, 3MF, and native GLB are mesh sidecars, not substitutes for STEP. Generate and validate STEP first, then export requested sidecars from the same `scripts/step` run. Do not treat sidecar renders as CAD validation; inspect the STEP, return `$render` viewer links for every generated or modified supported artifact, and use `$render` snapshots only when visual feedback is needed.

Native GLB sidecars are ordinary glTF 2.0 binary files for external tools: Y-up, meter-scaled, and free of the CAD Explorer `STEP_topology` extension. Do not confuse them with the hidden `.<name>.step.glb` Explorer topology artifact.

## Tool

Use `scripts/step` with a generated Python source:

```bash
python scripts/step path/to/model.py \
  --stl meshes/model.stl \
  --3mf meshes/model.3mf \
  --glb meshes/model.glb
```

When a generator exists, use the generator form. Use direct STEP/STP targets only when the generator is unavailable or the user explicitly identifies that file as the target:

```bash
python scripts/step --kind part path/to/model.step \
  --stl meshes/model.stl \
  --3mf meshes/model.3mf \
  --glb meshes/model.glb
```

Sidecar paths must be relative `.stl`, `.3mf`, or `.glb` paths and are resolved beside the STEP output.

## Mesh tolerance

Use these flags when the default mesh density is wrong for the part:

```bash
--mesh-tolerance FLOAT
--mesh-angular-tolerance FLOAT
```

Use tighter tolerances for small curved parts or visual fidelity. Use looser tolerances for large simple geometry when file size matters.

## Workflow

1. Generate STEP from `gen_step()` with the requested sidecar flag(s).
2. Run facts/planes/positioning inspection on the STEP.
3. Return the STEP, requested sidecar files, and `$render` viewer links for every generated or modified supported artifact when available.

Example:

```bash
python scripts/step models/bracket.py \
  --stl meshes/bracket.stl \
  --glb meshes/bracket.glb \
  --mesh-tolerance 0.2 \
  --mesh-angular-tolerance 0.2

python scripts/inspect refs models/bracket.step --facts --planes --positioning
```

## Reporting

```text
Files:
- STEP: models/bracket.step
- STL: meshes/bracket.stl
- GLB: meshes/bracket.glb

CAD Explorer:
- STEP: http://127.0.0.1:4178/?file=models/bracket.step
- STL: http://127.0.0.1:4178/?file=meshes/bracket.stl
- GLB: http://127.0.0.1:4178/?file=meshes/bracket.glb

Validation:
- STEP geometry validated; STL/3MF/native GLB generated as requested sidecars.
- Saved snapshot packet run/skipped and why.
```
