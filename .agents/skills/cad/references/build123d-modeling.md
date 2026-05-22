# build123d modeling patterns

Read this file when writing or repairing build123d Python source.

## Modeling objective

Create a valid STEP-ready BREP model, not a visual mesh. Prefer closed solids, explicit labels, and stable parametric dimensions.

## Topology stack

Think in this order:

```text
Vertex → Edge → Wire → Face → Shell → Solid → Compound
```

For normal STEP output, return one of:

- a valid `Solid`
- a compound of valid solids
- a labeled assembly compound

Avoid returning loose wires, open faces, or construction surfaces unless the user explicitly requested them.

## Source envelope

Generated sources should define:

```python
def gen_step():
    ...
    return shape_or_compound
```

Do not hardcode output paths inside `gen_step()`. The CLI owns output paths.

## Parameters first

Put meaningful dimensions in named variables:

```python
width = 80.0
depth = 50.0
thickness = 6.0
hole_diameter = 4.5
hole_offset_x = 30.0
hole_offset_y = 17.5
```

Avoid burying important numbers inside geometry calls.

## Coordinate system

Declare or comment the convention:

```text
Origin: center of primary part or chosen mating datum
XY: main base/sketch plane
+Z: up/extrusion direction
```

Use `Location`, `Plane`, and `Axis` intentionally. For positioning-sensitive tasks and source-level assembly relationships, read `positioning.md`.

## Builder contexts

Use the context that matches the geometry:

```python
with BuildLine() as path:
    ...

with BuildSketch() as profile:
    ...

with BuildPart() as part:
    ...
```

Typical flow:

```text
curves/paths → sketches/profiles → solids/features → labels → STEP
```

## Primitives

Use canonical primitives when they fit the design intent:

- `Box` for rectangular blocks and plates
- `Cylinder` for bosses, rods, pins, and subtractive cylindrical cuts
- `Sphere` for knobs or spherical ends
- `Torus` for rings and circular sweeps
- `Cone` for tapered features
- `Wedge` for sloped solids

Use sketches plus `extrude`, `revolve`, `sweep`, or `loft` when the shape is profile-driven.

## Feature operations

Map design intent to operations:

```text
hole              → Hole or subtractive cylinder
counterbore       → CounterBoreHole
countersink       → CounterSinkHole
slot              → slot profile + subtractive extrude
boss/standoff     → cylinder addition + central hole
rib               → extruded rectangular/triangular profile
rounded edge      → fillet
beveled edge      → chamfer
hollow enclosure  → shell or subtractive inner volume
revolved part     → revolve profile
swept tube/rail   → sweep profile along path
```

## Selection practices

Avoid fragile topology order when possible. Select by:

- axis or normal
- location or bounding position
- plane grouping
- feature intent
- stable construction plane
- inspected `@cad[...]` reference for downstream validation

For source operations, prefer robust selectors such as top/bottom by axis or position rather than arbitrary list indexes.


## Assemblies and positioning

For assemblies, keep this file focused on BREP modeling patterns and labels. Use `positioning.md` as the single source of truth for:

- part-local coordinate conventions
- when to use build123d joints versus explicit `Location` transforms
- `connect_to()` behavior
- CLI `inspect mate` as read-only validation
- frame, measure, and positioning report expectations

## Labels and assemblies

Label every exported part and assembly child:

```python
base.label = "base"
lid.label = "lid"
assembly.label = "electronics_enclosure"
```

For repeated parts, keep transforms or joint connections explicit and inspect frames/positioning after generation.

## Common failure modes

- Fillet radius larger than local edge geometry.
- Subtractive tool does not pass fully through target material.
- Open sketch profile produces invalid or missing face.
- Face selector changes after a boolean or fillet.
- Source-level assembly composition is lost by re-importing generated STEP instead of using the Python assembly source.
- Part origin is arbitrary and later mating checks become ambiguous.
- Joint labels are duplicated within the same part.
- Source-level joints are treated as if they were persistent STEP constraints rather than one-time source placement operations.
- Joint labels are missing, duplicated, or attached to the wrong local datum.
- `.connect_to()` fixes the wrong side of the relationship, moving the part intended to remain fixed.

Use `repair-loop.md` when generation or validation fails.
