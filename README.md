# CAD Power Animations

Parametric CAD models that explain how mechanical power flows through real
machines, built entirely with open-source tools and rendered live in a
static three.js viewer that ships to GitHub Pages.

Two models live here today:

| Model      | Story                                                                          |
| ---------- | ------------------------------------------------------------------------------ |
| F1 race car | Four-cylinder cut-away engine. Pistons push → crank rotates → drive shaft → differential → rear wheels. |
| Bicycle    | Crank arm → chainring → chain → rear cog → rear wheel → bike rolls forward.    |

## Stack

- **[build123d](https://github.com/gumyr/build123d)** — Python parametric CAD,
  generates the assembly as a labeled `Compound` of solids.
- **[CAD Skills](https://www.cadskills.xyz/)** (`earthtojake/text-to-cad`) —
  agent-skill toolkit that handles STEP generation, GLB/topology export, and
  CAD Explorer rendering.
- **`.<name>.step.js` sidecar** — a tiny ES module per model that exports a
  `manifest` (parameter definitions + occurrence-id features) and an
  `update(ctx)` function that drives part transforms from the live parameters.
  The same sidecar runs inside the CAD Explorer locally **and** in the static
  Pages viewer.
- **`site/`** — a hand-rolled three.js viewer (~500 LOC) that loads the GLB,
  reparents each top-level `o1.N` occurrence into a wrapper group, and runs
  the sidecar's `update()` every frame to apply matrices and colors.

## Layout

```
models/
  f1_car/
    f1_car.py          # build123d generator
    f1_car.step        # exported STEP (one solid compound)
    .f1_car.step.glb   # mesh + STEP_topology extension
    .f1_car.step.js    # animation sidecar
    renders/           # PNG / GIF previews used as thumbnails
  bicycle/
    bicycle.py
    bicycle.step
    .bicycle.step.glb
    .bicycle.step.js
    renders/

site/
  index.html           # landing page (model cards)
  viewer.html          # generic ?model=... viewer page
  viewer.js            # three.js + STEP-module sidecar runner
  style.css
  build-models.sh      # copies models/ -> site/models/ for deployment

.agents/skills/        # CAD Skills installed via `npx skills add`
```

## Regenerating a model

```bash
source .venv/bin/activate
python .agents/skills/cad/scripts/step models/bicycle/bicycle.py
```

This rewrites `bicycle.step`, the hidden `.bicycle.step.glb`, and assorted
topology sidecars. Open it locally with:

```bash
npm --prefix .agents/skills/render/scripts/viewer run dev:ensure -- \
  --workspace-root "$PWD" --file models/bicycle/bicycle.step
```

## Adding a new model

1. Drop a new `<name>.py` in `models/<name>/` that exposes a `gen_step()`
   returning a labeled `Compound`.
2. Generate `models/<name>/<name>.step` with the launcher above.
3. Write `models/<name>/.<name>.step.js` (ES module exporting
   `{ manifest, update(ctx) }`). Reference parts by `#o1.N` selectors in
   `manifest.features`.
4. Render a hero PNG (`models/<name>/renders/hero.png`) so the landing card
   has a thumbnail.
5. Register the model in `site/viewer.js` `MODELS = { ... }`.
6. Add a card to `site/index.html`.

## Deploying to GitHub Pages

A GitHub Actions workflow (`.github/workflows/pages.yml`) bundles `site/` +
the necessary files from `models/` and publishes them to Pages on every
push to `main`. After the first run, enable Pages in the repository
**Settings → Pages → Build and deployment → GitHub Actions**.
