# Positioning logic, joints, and mating

Read this file when geometry has mating interfaces, repeated features, assembly children, axes, datums, motion, or user-specified alignment. This is the authoritative reference for assembly positioning, build123d joints, explicit `Location` transforms, CLI `inspect mate`, and positioning report content.

## Core rule

Positioning is authored in source and validated after generation. Do not position parts by visually dragging or by editing exported STEP geometry. Use build123d parameters, local coordinate systems, `Location` transforms, `Plane`/`Axis` datums, source-level `Joint` objects when useful, and labeled assembly children.

## Terminology

Use these terms carefully:

- **build123d joints** are source-level objects such as `RigidJoint`, `RevoluteJoint`, `LinearJoint`, `CylindricalJoint`, and `BallJoint`. They are attached to `Solid` or `Compound` objects and can reposition parts with `connect_to()`.
- **CLI `inspect mate`** is a validation tool. It computes a read-only translation delta between selected `@cad[...]` references. It does not edit source code or patch exported STEP files.
- **Mating intent** is the design relationship: flush, centered, coaxial, offset, hinge-like, slider-like, or otherwise datum-driven.

There is no general instruction to ignore the CLI because build123d has joints. Use build123d joints to express and compute source assembly placement where appropriate, then use CLI inspection to validate the generated STEP.

## Preferred assembly structure

For assemblies, prefer a mate/joint-driven structure over arbitrary transforms:

```text
root component
→ part-local coordinate systems
→ named datums / joint locations
→ source-level build123d joints or explicit parameterized Locations
→ labeled Compound assembly
→ refs/measure/frame/mate validation
```

A numeric `Location(...)` should usually correspond to a stated datum, offset, clearance, screw axis, face contact, or joint relationship.

## Part-local positioning

For each part, define a local coordinate convention before modeling:

```text
- Origin: center, base datum, mounting interface, or functional axis.
- XY plane: main sketch/base plane unless another datum is dominant.
- +Z: extrusion/up direction.
- Named dimensions: offsets, hole spacing, boss spacing, clearances.
- Datum features: mating faces, screw axes, centerlines, locating tabs, rails.
```

Good defaults:

- Symmetric standalone parts: origin at body center.
- Plates: origin at footprint center; thickness along Z.
- Enclosures: origin at footprint center; base/lid mating surfaces controlled by Z parameters.
- Shaft/knob/axisymmetric parts: origin on rotational axis.
- Mating adapter plates: origin on the primary mounting datum or center of the bolt pattern.

## Feature placement inside a part

Use named parameters and local coordinates:

```python
hole_offset_x = 30
hole_offset_y = 17.5
hole_positions = [
    (-hole_offset_x, -hole_offset_y),
    ( hole_offset_x, -hole_offset_y),
    (-hole_offset_x,  hole_offset_y),
    ( hole_offset_x,  hole_offset_y),
]

with Locations(*hole_positions):
    Hole(radius=hole_diameter / 2)
```

Avoid untraceable placement constants inside geometry calls. Put all meaningful offsets into parameters.

## When to use build123d joints

Use build123d joints when assembly intent is clearer as a relationship between part datums than as a raw transform:

- lid-to-base, cover-to-frame, bracket-to-rail, flange-to-pipe, pin-to-hole, shaft-to-bearing
- hinge, slider, screw-like, cylindrical, ball/gimbal, or other motion-positioned assemblies
- repeated or library components that already expose joints
- source assemblies where a change to one dimension should recompute part placement

Direct `Location(...)` transforms are acceptable for simple static layouts when they are parameterized and documented, such as a row of identical spacers or a visual exploded view.

## build123d joint pattern

Use build123d joints inside the Python source when they clarify placement. The exact joint locations should be named or derived from parameters.

```python
from build123d import *

base_height = 30.0
lid_thickness = 3.0
gasket_gap = 0.5

# base and lid are generated Solid or Compound objects.
base = make_base()
lid = make_lid()
base.label = "base"
lid.label = "lid"

# Fixed datum on the base: lid seats on this plane.
RigidJoint(
    label="lid_seat",
    to_part=base,
    joint_location=Location((0, 0, base_height / 2 + gasket_gap)),
)

# Datum on the moving lid: underside of the lid.
RigidJoint(
    label="underside",
    to_part=lid,
    joint_location=Location((0, 0, -lid_thickness / 2)),
)

# Reposition lid so lid.underside matches base.lid_seat.
base.joints["lid_seat"].connect_to(lid.joints["underside"])

assembly = Compound(label="enclosure", children=[base, lid])
```

`connect_to()` is a source-generation operation. It repositions the moving part for the generated model; it is not a persistent external constraint in the exported STEP file.

## Joint type selection

Use the simplest joint that expresses the source-level relationship:

- `RigidJoint`: fixed placement, face-to-face seating, mounting datums, imported components with known interfaces.
- `RevoluteJoint`: hinge or rotational pose; drive with an angle parameter for a static STEP pose.
- `LinearJoint`: slider, latch, telescoping component; drive with a position parameter.
- `CylindricalJoint`: combined axial translation and rotation, such as screw-like or pin-in-slot relationships.
- `BallJoint`: gimbal or spherical orientation relationship.

When only final static placement matters and no meaningful joint datum exists, use explicit `Location` transforms and validate them.

## Assembly positioning workflow

1. Choose the fixed/root component.
2. Define part-local frames and datums before modeling child placement.
3. Identify functional datums such as mating faces, screw axes, hinge axes, sliding axes, locating tabs, gasket offsets, or contact planes.
4. Name source-level joints or mating datums on each child.
5. Use build123d joints where they improve source clarity, otherwise use parameterized `Location` transforms.
6. Build a labeled `Compound` assembly.
7. Generate the assembly through the Python source, not by re-importing the generated STEP:

```bash
python scripts/step path/to/assembly.py
python scripts/inspect refs path/to/assembly.step --facts --planes --positioning
```

Passing a generated assembly STEP directly treats it as imported native STEP and does not preserve source-level composition semantics.

## CLI mating validation

After generation, use CLI inspection to validate the STEP result:

```bash
python scripts/inspect refs path/to/assembly.step \
  --facts --planes --positioning
```

Then select moving and target references from the returned `@cad[...]` refs and compute read-only deltas:

```bash
python scripts/inspect mate \
  --moving '@cad[path/to/assembly.step#moving_selector]' \
  --target '@cad[path/to/assembly.step#target_selector]' \
  --mode flush \
  --axis z
```

Use `--mode flush` for coplanar face alignment. Use `--mode center` for centerline, plane-center, or symmetrical alignment where supported by the selected references. If the returned delta is outside tolerance, edit the build123d source placement or joint location, regenerate, and rerun inspection.

## Frame validation

Use `frame` to inspect an occurrence or selector's world frame:

```bash
python scripts/inspect frame '@cad[path/to/assembly.step#selector]'
```

Use this when:

- a child appears in the wrong orientation
- a mating face is offset in world coordinates
- an axis is expected to align with X/Y/Z
- repeated parts should share orientation
- a downstream task needs a stable coordinate frame

## Measurement validation

Use `measure` for scalar checks:

```bash
python scripts/inspect measure \
  --from '@cad[path/to/assembly.step#selector_a]' \
  --to '@cad[path/to/assembly.step#selector_b]' \
  --axis z
```

Examples:

- lid bottom face to base top face should be 0 mm for flush contact
- two screw axes should have matching X/Y positions
- bracket mounting face should sit a specified distance from a datum plane
- spacer height should equal requested offset

## Source-level positioning corrections

When a positioning check fails, fix one of these in source:

- child `Location` translation
- child `Location` rotation
- build123d joint location or axis
- part-local origin convention
- feature offset parameter
- sketch plane
- workplane selection
- assembly hierarchy
- symmetric placement signs

Then regenerate. Do not patch the exported STEP directly.

## Reporting positioning

In the final response, report only checks that were run:

```text
Positioning/joints:
- source used RigidJoint lid_seat → underside
- base/lid Z mate: flush, delta 0.00 mm
- screw boss axis alignment: checked in XY by measurement
- lid occurrence frame: +Z up, origin at assembly centerline
```

If no positioning-sensitive features exist, say:

```text
Positioning: not applicable beyond centered part-local origin.
```

If a mate or alignment was intended but not checked, say `not checked`; do not imply success.
