# Repair loop

Read this file when generation, export, inspection, positioning, render review, Explorer setup, or documentation validation fails.

## Loop

1. Read the failing command output.
2. Classify the failure.
3. Make the smallest responsible source or command change.
4. Rerun the failed command.
5. Rerun any dependent validation checks.
6. Report remaining risk or deliberate deviations.

## Failure classes and fixes

### Source import or syntax failure

Likely causes:

- invalid Python syntax
- missing import
- wrong build123d symbol
- function not named `gen_step()`
- executable code outside the intended function has side effects

Fix:

- correct imports and syntax
- ensure `gen_step()` returns the STEP-ready shape or compound
- keep output paths in CLI commands, not inside `gen_step()`

### Invalid or missing geometry

Likely causes:

- open sketch
- subtractive profile outside target
- zero thickness
- boolean operation failed
- construction geometry used as exported geometry

Fix:

- close profiles intended to become faces
- verify dimensions are positive
- make subtractive tools pass through when through-cuts are intended
- simplify the failing feature and rebuild incrementally

### Fillet or chamfer failure

Likely causes:

- radius/length exceeds local geometry
- selected edges include tiny or unintended edges
- boolean operation created complex edge topology

Fix:

- reduce radius/length
- filter selected edges more narrowly
- apply fillets later in the model
- split edge groups by feature intent

### Wrong scale or bounding box

Likely causes:

- units mismatch
- mistaken diameter/radius
- extrusion direction or amount wrong
- part not centered as assumed
- direct imported STEP uses unexpected units

Fix:

- check parameter values
- inspect facts and planes
- measure critical extents
- correct source dimensions or import handling

### Missing feature

Likely causes:

- wrong `Mode.ADD`/`Mode.SUBTRACT`
- feature profile not inside target
- blind cut too shallow
- selector changed after prior operation

Fix:

- confirm feature mode
- increase cut length for through-cuts
- inspect topology or planes
- regenerate and measure/check feature-specific refs

### Selector fragility

Likely causes:

- arbitrary index selection
- topology changed after fillet or boolean
- similar faces/edges are indistinguishable

Fix:

- select by axis, plane, position, normal, or inspected reference
- use `refs --facts --planes --positioning` to rediscover stable references
- add construction datums or simplify operations if needed

### Positioning or joint mismatch

Likely causes:

- wrong part-local origin
- child `Location` offset wrong
- build123d joint attached to the wrong datum
- `.connect_to()` moved the wrong part
- joint axis or orientation inverted
- rotation applied about wrong axis
- sign error in symmetric placement
- mating face selected incorrectly

Fix:

- inspect `refs --positioning`
- run `frame` on relevant selectors or occurrences
- run `mate` for read-only delta
- apply correction to source build123d joint, `.connect_to()` call, `Location`, datum, or feature offset
- regenerate and remeasure

### Explorer startup or link failure

Likely causes:

- Node/npm unavailable
- Explorer app not built or cannot start
- scan root differs from assumed root
- returned file path is not relative to active scan root

Fix:

- hand the explicit artifact path to `$render`
- check `EXPLORER_ROOT_DIR` when available
- return the best documented link format
- report startup failure if unresolved
- rely on CLI facts/measurements for validation

### Explorer render failure

Likely causes:

- attempted to render Python source instead of an Explorer-visible artifact
- target path wrong
- Explorer/adjacent render artifact missing
- invalid render flags

Fix:

- generate STEP first
- snapshot `.step`, `.stp`, `.glb`, `.stl`, `.3mf`, `.dxf`, `.urdf`, `.srdf`, or `.sdf` with the render skill's snapshot CLI rather than manual viewer or Playwright inspection
- retry only with simpler supported render jobs, starting with a single `view` output before `wireframe` or `section`
- for CAD review packets, use still-image modes: `view`, `wireframe`, and `section`
- generate GIFs only for STEP-module parameter animation review
- rerender only after a source repair changed visible geometry or a specific visual finding needs confirmation
- skip saved snapshots when they are not needed under `render-review.md`

## Diff after repair

Use `diff` when the fix might have affected unrelated geometry:

```bash
python scripts/inspect diff path/to/before.step path/to/after.step --planes
```

## Reporting failed repairs

If a check cannot be repaired in the current environment, report:

```text
- what failed
- what was tried
- which artifact is still usable
- which validation claims cannot be made
- what the next source-level correction should be
```


### Joint or mating mismatch

Likely causes:

- wrong fixed/root component
- joint location defined in world coordinates when a part-local datum was intended
- joint orientation flipped
- duplicate or incorrect joint labels
- explicit `Location` not recomputed after a parameter change
- CLI `inspect mate` delta was treated as an edit instead of a diagnostic

Fix:

- inspect `refs --positioning` and `frame` for the affected occurrences
- verify the source-level build123d joint labels and `joint_location` definitions
- adjust the smallest joint location, axis, angle, position, or explicit transform
- regenerate the assembly from the Python source
- rerun `refs --facts --planes --positioning` plus the failed `measure` or `mate` check
