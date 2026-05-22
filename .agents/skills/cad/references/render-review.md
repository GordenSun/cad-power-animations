# Render review

Read this file when deciding whether to request saved `$render` snapshots after deterministic CAD validation.

## Principle

CAD Explorer links are the live handoff layer and should be returned for every generated or modified supported artifact when `$render` is available. Saved snapshots are the preferred visual-feedback layer for generation review; use the render skill's snapshot CLI instead of opening the viewer manually or using Playwright. Snapshots do not replace STEP generation, `scripts/inspect`, measurements, mating checks, frames, or diffs.

Do not request saved snapshots by default for:

- simple primitives or simple single-body blocks, plates, cylinders, spacers, and shafts
- pure format/export requests where geometry is unchanged
- source changes that do not alter visible geometry
- direct measurement questions answerable with `scripts/inspect`
- failed Python or STEP generation before a valid artifact exists

For those cases, generate or inspect the explicit target, use facts/planes/positioning and targeted measurements, hand off generated or modified artifacts to `$render` when available, and report the evidence.

## Risk triggers

After artifact generation and geometric validation pass, request one saved snapshot packet when semantic errors are plausible from shape complexity or prompt intent:

- assemblies or more than one body/part
- holes on multiple faces or multiple axes
- shells, internal cavities, bores, passages, open enclosures, or section-critical features
- ribs, gussets, bosses, standoffs, slots, cutouts, lightening holes, fins, blades, or repeated patterns
- source repairs after a geometry, boolean, selector, or feature failure
- prompts where "looks like the requested object" is part of the task
- deterministic checks pass but visible semantics are still uncertain

Do not loop on snapshots. Rerender only when a source repair changed visible geometry or when a specific visual finding needs confirmation. Generate GIFs only for STEP-module parameter animation review; otherwise use still snapshots, not GIFs.

## Small packet

Use a small packet first. Prefer a single `view` JSON job with these outputs:

```json
{
  "mode": "view",
  "outputs": [
    { "path": "/tmp/render/iso_shaded_edges.png", "camera": "iso", "width": 1600, "height": 1200 },
    { "path": "/tmp/render/front_ortho.png", "camera": "front", "width": 1600, "height": 1200 },
    { "path": "/tmp/render/top_ortho.png", "camera": "top", "width": 1600, "height": 1200 },
    { "path": "/tmp/render/right_ortho.png", "camera": "right", "width": 1600, "height": 1200 }
  ],
  "theme": { "id": "workbench", "settings": null },
  "render": { "viewLabels": true, "padding": 0.12, "sizeProfile": "diagnostic" }
}
```

Set `input`, `workspaceRoot`, and `rootDir` for the actual artifact. The snapshot CLI defaults to the `workbench` theme for flat diagnostic stills; labeled/section views default to 1600x1200 when dimensions are omitted. Use `render.sizeProfile: "assembly"` or `"assembly-large"` for complex assemblies that need 1800x1200 or 1920x1440. For CAD review packets, use still-image modes: `view`, `wireframe`, and `section`.

## Targeted additions

Add views only when the brief or a failure mode calls for them:

- rear or bottom camera: features may be hidden from the default packet
- `section`: shell, bore, internal cavity, passage, blind hole, enclosure, or wall/floor relationship
- `wireframe`: internal overlap, hidden interference, or assembly collision suspicion
- transparent theme settings in a JSON job: overlap, collision, or enclosure readability when transparency adds information and wireframe is too noisy; otherwise treat transparent views as presentation-only
- labeled or annotated review: use supported Explorer refs, selections, screenshots, or GUI review links

Exploded or labeled review is an intent, not a render mode. Satisfy it through supported Explorer mechanisms, supported JSON job settings, or the GUI link.

## Diagnostic review

Visual review is diagnostic, not authoritative. Convert every visual concern into a follow-up geometry check before using it as a validation claim:

- hole pattern appears asymmetric -> measure hole centers and compare offsets
- lid, child part, or occurrence appears offset -> inspect frames and mating deltas
- gusset, boss, standoff, rib, or plate may be floating -> inspect solid count, labels, connectivity, contact, or relevant distances
- cavity, bore, or blind hole looks wrong -> run section review, then measure wall thickness, depth, or through-condition
- repeated pattern looks uneven -> measure pattern centers, angular spacing, or occurrence frames

Final reports should say whether the `$render` viewer link was returned, whether a saved snapshot packet was run or skipped, why that decision was made, and which deterministic checks support any visual finding.
