/* Quadcopter sidecar.
 *
 *   drive (deg, animated 0..360) drives:
 *     prop spin = drive * prop_factor (paired CW/CCW for torque balance)
 *     hover bob = hover_amp * sin(drive)
 *     pitch     = pitch_amp * sin(drive - 90deg)  (one quarter ahead of bob)
 */

const BODY_Z = 220;
const MOTOR_DISTANCE = 360;
const _D = MOTOR_DISTANCE / Math.sqrt(2);
const MOTOR_POSITIONS = {
  fl: [+_D, +_D, BODY_Z],
  fr: [+_D, -_D, BODY_Z],
  rl: [-_D, +_D, BODY_Z],
  rr: [-_D, -_D, BODY_Z]
};
// Torque-balanced spin direction: FL & RR = CCW (+), FR & RL = CW (-)
const SPIN_DIR = { fl: +1, fr: -1, rl: -1, rr: +1 };

const DEG = Math.PI / 180;

// Every part that should move with the body as a rigid unit (everything except
// the four propellers, which add their own spin around the motor axis).
const BODY_PARTS = [
  "body", "landing_gear",
  "arm_fl", "arm_fr", "arm_rl", "arm_rr",
  "motor_fl", "motor_fr", "motor_rl", "motor_rr"
];

export default {
  manifest: {
    schemaVersion: 1,
    parameters: {
      drive: {
        type: "number",
        label: "Hover cycle",
        description: "One full sweep (0–360 deg) = one hover bob + one pitch oscillation.",
        unit: "deg",
        min: 0,
        max: 360,
        step: 1,
        default: 0
      },
      prop_factor: {
        type: "number",
        label: "Prop revolutions / cycle",
        description: "Propeller turns per hover cycle. Higher = faster spin.",
        min: 2,
        max: 24,
        step: 1,
        default: 8
      },
      hover_amp: {
        type: "number",
        label: "Hover amplitude (mm)",
        min: 0,
        max: 200,
        step: 5,
        default: 90
      },
      pitch_amp: {
        type: "number",
        label: "Pitch amplitude (deg)",
        min: 0,
        max: 30,
        step: 1,
        default: 14
      }
    },
    features: {
      body:          { ref: "#o1.1" },
      landing_gear:  { ref: "#o1.2" },
      arm_fl:        { ref: "#o1.3" },
      arm_fr:        { ref: "#o1.4" },
      arm_rl:        { ref: "#o1.5" },
      arm_rr:        { ref: "#o1.6" },
      motor_fl:      { ref: "#o1.7" },
      motor_fr:      { ref: "#o1.8" },
      motor_rl:      { ref: "#o1.9" },
      motor_rr:      { ref: "#o1.10" },
      prop_fl:       { ref: "#o1.11" },
      prop_fr:       { ref: "#o1.12" },
      prop_rl:       { ref: "#o1.13" },
      prop_rr:       { ref: "#o1.14" }
    },
    animations: {
      hover: { duration: 5, loop: true }
    }
  },

  update(ctx) {
    const { params, effects } = ctx;
    const driveDeg = Number(params.drive) || 0;
    const drive = driveDeg * DEG;
    const propFactor = Number(params.prop_factor) || 8;
    const hoverAmp = Number(params.hover_amp) || 90;
    const pitchAmp = Number(params.pitch_amp) || 14;

    // ---- Bright styling ----
    effects.style("body",         { color: "#facc15", emissive: "#854d0e", emissiveIntensity: 0.4 });
    effects.style("landing_gear", { color: "#fde047" });
    for (const arm of ["fl", "fr", "rl", "rr"]) {
      effects.style(`arm_${arm}`,  { color: "#ef4444" });
      effects.style(`motor_${arm}`,{ color: "#a78bfa", emissive: "#4c1d95", emissiveIntensity: 0.2 });
      effects.style(`prop_${arm}`, { color: "#22d3ee", emissive: "#0e7490", emissiveIntensity: 0.35 });
    }

    // ---- Body motion: bob + pitch around its own centre ----
    const bobZ = hoverAmp * Math.sin(drive);
    const pitchDeg = pitchAmp * Math.sin(drive - Math.PI / 2);

    const bodyT = {
      transforms: [
        { rotate: { axis: [0, 1, 0], origin: [0, 0, BODY_Z], angleDeg: pitchDeg } },
        { translate: [0, 0, bobZ] }
      ]
    };
    for (const id of BODY_PARTS) {
      effects.transform(id, bodyT);
    }

    // ---- Propellers: spin around motor axis (Z), then ride the body ----
    const propBaseDeg = driveDeg * propFactor;
    for (const m of ["fl", "fr", "rl", "rr"]) {
      const pos = MOTOR_POSITIONS[m];
      const spin = propBaseDeg * SPIN_DIR[m];
      effects.transform(`prop_${m}`, {
        transforms: [
          { rotate: { axis: [0, 0, 1], origin: pos, angleDeg: spin } },
          { rotate: { axis: [0, 1, 0], origin: [0, 0, BODY_Z], angleDeg: pitchDeg } },
          { translate: [0, 0, bobZ] }
        ]
      });
    }
  }
};
