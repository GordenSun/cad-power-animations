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
        description: "Translate the whole bike along +X to show the resulting motion.",
        default: true
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
    const wheelAngleDeg = -cadenceDeg * ratio;
    // Forward distance from pure rolling: arc = wheel_radius * angle_rad
    const distance = roll
      ? cadenceRad * ratio * WHEEL_RADIUS * rollScale
      : 0;
    const rollT = [distance, 0, 0];

    // ---- Styling (must re-apply each frame; see cadScene.resetParameterEffects) ----
    effects.style("frame",       { color: "#0ea5e9" });   // sky blue
    effects.style("fork",        { color: "#0369a1" });
    effects.style("handlebar",   { color: "#1e293b" });
    effects.style("seat",        { color: "#1f2937" });
    effects.style("wheel_front", { color: "#111827" });   // tyre
    effects.style("wheel_rear",  { color: "#111827" });
    effects.style("crank_left",  { color: "#fbbf24" });   // brass crank arms
    effects.style("crank_right", { color: "#fbbf24" });
    effects.style("pedal_left",  { color: "#ef4444" });   // red pedals so motion reads
    effects.style("pedal_right", { color: "#ef4444" });
    effects.style("chainring",   { color: "#f59e0b", emissive: "#78350f", emissiveIntensity: 0.15 });
    effects.style("rear_cog",    { color: "#f59e0b", emissive: "#78350f", emissiveIntensity: 0.15 });
    effects.style("chain",       { color: "#94a3b8" });   // grey chain

    // ---- Frame + non-rotating bits: just slide forward when rolling ----
    for (const id of ["frame", "fork", "handlebar", "seat", "chain"]) {
      effects.transform(id, { translate: rollT });
    }

    // ---- Cranks + chainring: rotate around BB, then translate ----
    // Rotation around +Y by -cadenceDeg keeps the "forward pedal goes up"
    // visual matching a real bike when viewed from the right side (-Y).
    const crankSpec = {
      transforms: [
        { rotate: { axis: [0, 1, 0], origin: BB, angleDeg: -cadenceDeg } },
        { translate: rollT }
      ]
    };
    effects.transform("crank_left", crankSpec);
    effects.transform("crank_right", crankSpec);
    effects.transform("chainring", crankSpec);

    // ---- Pedals: only translate (bearings keep them level) ----
    // Left pedal initial position relative to BB is (0, +75, -CRANK_LENGTH).
    // After rotating crank by -cadence around Y, the pedal mount lands at
    //   ( CRANK_LENGTH*sin(cadence), +75, -CRANK_LENGTH*cos(cadence) )
    // so the pedal must translate by the delta.
    const sinT = Math.sin(cadenceRad);
    const cosT = Math.cos(cadenceRad);
    const pedalDx = CRANK_LENGTH * sinT;
    const pedalDz = CRANK_LENGTH * (1 - cosT);
    effects.transform("pedal_left",  { translate: [ pedalDx + distance, 0,  pedalDz] });
    effects.transform("pedal_right", { translate: [-pedalDx + distance, 0, -pedalDz] });

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
