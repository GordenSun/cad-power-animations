/* Bicycle STEP module sidecar.
 *
 * Drives the "forward motion" animation:
 *   rider torque on pedal -> crank arm + chainring rotate around the
 *   bottom bracket -> chain transfers the rotation to the rear cog ->
 *   rear cog spins the rear wheel -> rolling friction translates the
 *   bike forward (and rolls the front wheel along).
 *
 * Pedals are mounted on bearings, so they stay level (translated only,
 * not rotated). All geometry constants below must mirror bicycle.py.
 */

// ---- Geometry constants (must match bicycle.py) ----
const WHEEL_RADIUS = 350;
const WHEELBASE = 1010;
const FRONT_HUB_X = WHEELBASE / 2;        // +505
const REAR_HUB_X = -WHEELBASE / 2;        // -505
const CHAINSTAY_LENGTH = 410;
const BB_DROP = 70;
const BB_X = REAR_HUB_X + Math.sqrt(CHAINSTAY_LENGTH * CHAINSTAY_LENGTH - BB_DROP * BB_DROP); // ~-101.4
const BB_Z = WHEEL_RADIUS - BB_DROP;      // 280
const BB = [BB_X, 0, BB_Z];
const CRANK_LENGTH = 170;
const REAR_HUB = [REAR_HUB_X, 0, WHEEL_RADIUS];
const FRONT_HUB = [FRONT_HUB_X, 0, WHEEL_RADIUS];

const DEG = Math.PI / 180;

export default {
  manifest: {
    schemaVersion: 1,
    parameters: {
      cadence: {
        type: "number",
        label: "Pedal angle",
        description: "Crank rotation. One full pedal stroke = 360 deg.",
        unit: "deg",
        min: 0,
        max: 720,
        step: 1,
        default: 0
      },
      gear_ratio: {
        type: "number",
        label: "Gear ratio (chainring / cog)",
        description: "Real bikes are ~2-5. Higher = wheel turns faster per pedal stroke.",
        min: 1,
        max: 5,
        step: 0.1,
        default: 2.5
      },
      roll_forward: {
        type: "boolean",
        label: "Roll forward",
        description: "Translate the whole bike along +X to show the resulting motion. Off by default so the animation stays in frame.",
        default: false
      },
      roll_scale: {
        type: "number",
        label: "Roll distance scale",
        description: "Visual scale applied to the rolled distance (1.0 = real-world).",
        min: 0.0,
        max: 1.0,
        step: 0.05,
        default: 0.25
      }
    },
    features: {
      frame:        { ref: "#o1.1" },
      fork:         { ref: "#o1.2" },
      handlebar:    { ref: "#o1.3" },
      seat:         { ref: "#o1.4" },
      wheel_front:  { ref: "#o1.5" },
      wheel_rear:   { ref: "#o1.6" },
      crank_left:   { ref: "#o1.7" },
      crank_right:  { ref: "#o1.8" },
      pedal_left:   { ref: "#o1.9" },
      pedal_right:  { ref: "#o1.10" },
      chainring:    { ref: "#o1.11" },
      rear_cog:     { ref: "#o1.12" },
      chain:        { ref: "#o1.13" }
    },
    animations: {
      pedal_cycle: { duration: 4, loop: true }
    }
  },

  /**
   * Per-frame update. Idempotent; the viewer resets all part effects
   * between calls, so re-apply styles AND transforms every frame.
   */
  update(ctx) {
    const { params, effects } = ctx;
    const cadenceDeg = Number(params.cadence) || 0;
    const ratio = Math.max(Number(params.gear_ratio) || 2.5, 0.1);
    const roll = params.roll_forward !== false;
    const rollScale = Math.max(Number(params.roll_scale) ?? 0.25, 0);

    const cadenceRad = cadenceDeg * DEG;
    // Forward pedaling: viewed from the right side of the bike, the cranks
    // and wheels turn clockwise (top moves toward +X). Around the +Y axis
    // that's a positive right-hand-rule rotation.
    const wheelAngleDeg = cadenceDeg * ratio;
    // Forward distance from pure rolling: arc = wheel_radius * angle_rad
    const distance = roll
      ? cadenceRad * ratio * WHEEL_RADIUS * rollScale
      : 0;
    const rollT = [distance, 0, 0];

    // ---- Bright styling so every part stays readable on the dark viewer bg ----
    effects.style("frame",       { color: "#22d3ee" });   // bright cyan
    effects.style("fork",        { color: "#a78bfa" });   // violet
    effects.style("handlebar",   { color: "#fde047" });   // bright yellow
    effects.style("seat",        { color: "#f472b6" });   // hot pink
    effects.style("wheel_front", { color: "#fb923c" });   // bright orange
    effects.style("wheel_rear",  { color: "#fb923c" });
    effects.style("crank_left",  { color: "#facc15", emissive: "#854d0e", emissiveIntensity: 0.25 });
    effects.style("crank_right", { color: "#facc15", emissive: "#854d0e", emissiveIntensity: 0.25 });
    effects.style("pedal_left",  { color: "#ef4444", emissive: "#7f1d1d", emissiveIntensity: 0.25 });
    effects.style("pedal_right", { color: "#ef4444", emissive: "#7f1d1d", emissiveIntensity: 0.25 });
    effects.style("chainring",   { color: "#fde047", emissive: "#a16207", emissiveIntensity: 0.3 });
    effects.style("rear_cog",    { color: "#fde047", emissive: "#a16207", emissiveIntensity: 0.3 });
    effects.style("chain",       { color: "#e2e8f0" });   // bright pale silver

    // ---- Frame + non-rotating bits: just slide forward when rolling ----
    for (const id of ["frame", "fork", "handlebar", "seat", "chain"]) {
      effects.transform(id, { translate: rollT });
    }

    // ---- Cranks + chainring: rotate around BB, then translate ----
    // Positive rotation around +Y is "top moves toward +X" - the natural
    // forward pedalling direction viewed from the right side of the bike.
    const crankSpec = {
      transforms: [
        { rotate: { axis: [0, 1, 0], origin: BB, angleDeg: cadenceDeg } },
        { translate: rollT }
      ]
    };
    effects.transform("crank_left", crankSpec);
    effects.transform("crank_right", crankSpec);
    effects.transform("chainring", crankSpec);

    // ---- Pedals: only translate (bearings keep them level) ----
    // Right pedal initial: (0, -75, +CRANK_LENGTH); after R_y(+cadence) it
    // lands at ( L sin t, -75,  L cos t).  Left pedal initial:
    // (0, +75, -CRANK_LENGTH); after R_y(+cadence) it lands at
    // (-L sin t, +75, -L cos t).
    const sinT = Math.sin(cadenceRad);
    const cosT = Math.cos(cadenceRad);
    const pedalDx = CRANK_LENGTH * sinT;       // = L sin t
    const oneMinusCos = CRANK_LENGTH * (1 - cosT);
    effects.transform("pedal_right", { translate: [ pedalDx + distance, 0, -oneMinusCos] });
    effects.transform("pedal_left",  { translate: [-pedalDx + distance, 0,  oneMinusCos] });

    // ---- Wheels + rear cog: rotate around hub, then translate ----
    effects.transform("wheel_rear", {
      transforms: [
        { rotate: { axis: [0, 1, 0], origin: REAR_HUB, angleDeg: wheelAngleDeg } },
        { translate: rollT }
      ]
    });
    effects.transform("rear_cog", {
      transforms: [
        { rotate: { axis: [0, 1, 0], origin: REAR_HUB, angleDeg: wheelAngleDeg } },
        { translate: rollT }
      ]
    });
    effects.transform("wheel_front", {
      transforms: [
        { rotate: { axis: [0, 1, 0], origin: FRONT_HUB, angleDeg: wheelAngleDeg } },
        { translate: rollT }
      ]
    });
  }
};
