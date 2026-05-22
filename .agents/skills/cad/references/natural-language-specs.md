# Natural-language CAD specs

Read this file when converting a user's prose request into a CAD brief. Do not require the user to provide JSON. If the user supplied JSON voluntarily, extract the same information but continue the workflow in prose notes and build123d source.

## Goal

Convert natural-language requirements into an actionable modeling brief before writing source or running tools.

The brief should answer:

- What is being modeled?
- Is it a part, assembly, modification, inspection task, or secondary output request?
- What dimensions and units are specified?
- Which dimensions are missing but inferable?
- Which features are required?
- Which faces, axes, origins, joints, or interfaces control positioning?
- What output files are requested?
- What must be validated before success is reported?

## Brief format

Use concise Markdown notes, not a user-facing structured schema.

Recommended structure:

```text
CAD brief:
- Model: <part or assembly name>
- Output: STEP primary; secondary outputs if requested
- Units: <explicit or assumed>
- Coordinate convention: <origin, base plane, up axis>
- Overall dimensions: <width/depth/height or equivalent>
- Functional features: <holes, slots, ribs, bosses, pockets, shells, text, etc.>
- Positioning/mating: <interfaces, datums, child placements, native joint opportunities, alignment rules>
- Validation targets: <bbox, solid count, labels, measurements, refs>
- Assumptions: <only meaningful inferred choices>
```

## Example: simple part

User says:

```text
Make a 100 mm by 60 mm by 6 mm mounting plate with rounded corners, four M4 clearance holes 10 mm in from the corners, and a 20 by 12 mm rectangular cutout in the center.
```

Agent brief:

```text
CAD brief:
- Model: mounting_plate, single STEP part.
- Units: millimeters.
- Origin: center of plate; base plane XY; +Z is thickness direction.
- Body: rounded rectangular plate, 100 × 60 × 6 mm.
- Corner radius: not specified; assume 3 mm.
- Holes: four 4.5 mm M4 clearance through-holes, 10 mm in from each corner.
- Cutout: centered rectangular through-cut, 20 × 12 mm.
- Validation: one positive-volume solid, bbox 100 × 60 × 6 mm, four holes, one center cutout, label mounting_plate.
- Render: return `$render` viewer link to the STEP file when available.
```

## Example: assembly

User says:

```text
Design a two-piece enclosure, 120 by 80 by 35 mm, with a lid that sits on top and four screw bosses aligned between base and lid.
```

Agent brief:

```text
CAD brief:
- Model: enclosure assembly with base and lid.
- Units: millimeters.
- Assembly origin: center of enclosure footprint; +Z upward.
- Base: hollow lower shell, exterior 120 × 80 mm footprint; height derived from total height minus lid thickness.
- Lid: separate plate on top; assume 3 mm lid thickness unless user gave another value.
- Bosses: four aligned screw bosses; assume M3 unless unspecified dimensions make this unsafe.
- Positioning: base top face and lid bottom face are mating datums; screw axes must align; native build123d joints may be used if they clarify reusable mount points or motion.
- Validation: labeled base and lid children, bbox near 120 × 80 × 35 mm, aligned hole/boss axes, Explorer link returned.
```

## Clarification policy

Ask one focused question only when the missing information affects fit, safety, compliance, or makes the part impossible to model. Otherwise proceed with assumptions and report them.

Ask when:

- No dimensions are provided for a physical object.
- A mating interface is described but the mating geometry is unspecified.
- The part is safety-critical, load-bearing, pressure-bearing, medical, or compliance-bound.
- The requested output depends on an absent source file or missing imported geometry.

Do not ask when:

- A default clearance hole standard is sufficient.
- A cosmetic fillet radius can be safely assumed.
- Origin/orientation can be chosen and reported.
- The user is asking for a conceptual first-pass CAD model.

## Success criteria

A brief is ready for modeling when it contains enough information to define:

- source file path
- STEP target path
- units
- local coordinate system
- named parameters
- feature plan
- labels
- expected bounding box or key measurements
- Explorer link target
