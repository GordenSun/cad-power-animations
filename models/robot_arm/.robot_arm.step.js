/* Robot arm STEP module sidecar.
 *
 * 5-DOF articulated arm with parallel-jaw gripper. Each joint adds a
 * rotation to the kinematic chain - the per-part `transforms` array
 * stacks the upstream joint rotations so each link is composed
 * correctly without needing a runtime three.js scene graph.
 *
 * Joint axes (right-hand rule):
 *   J0  base yaw    around +Z at base
 *   J1  shoulder    around +Y at column top
 *   J2  elbow       around +Y at end of upper arm
 *   J3  wrist pitch around +Y at end of forearm
 *   J4  tool roll   around +X at end of wrist
 *
 * Geometry constants below must mirror robot_arm.py.
 */

const COLUMN_TOP_Z = 290;
const UPPER_ARM_LENGTH = 260;
const FOREARM_LENGTH = 220;
const WRIST_LENGTH = 110;

const J0 = [0, 0, 0];
const J1 = [0, 0, COLUMN_TOP_Z];
const J2 = [UPPER_ARM_LENGTH, 0, COLUMN_TOP_Z];
const J3 = [UPPER_ARM_LENGTH + FOREARM_LENGTH, 0, COLUMN_TOP_Z];
const J4 = [UPPER_ARM_LENGTH + FOREARM_LENGTH + WRIST_LENGTH, 0, COLUMN_TOP_Z];

const DEG = Math.PI / 180;

// Kinematic chain helper: returns a transforms[] array that composes the
// joints in the upstream-to-current order. `transforms[0]` is applied to
// the vertex first; later steps wrap around it.
function chain(j0, j1, j2, j3, j4) {
  const stack = [];
  if (j4 !== undefined) stack.push({ rotate: { axis: [1, 0, 0], origin: J4, angleDeg: j4 } });
  if (j3 !== undefined) stack.push({ rotate: { axis: [0, 1, 0], origin: J3, angleDeg: j3 } });
  if (j2 !== undefined) stack.push({ rotate: { axis: [0, 1, 0], origin: J2, angleDeg: j2 } });
  if (j1 !== undefined) stack.push({ rotate: { axis: [0, 1, 0], origin: J1, angleDeg: j1 } });
  if (j0 !== undefined) stack.push({ rotate: { axis: [0, 0, 1], origin: J0, angleDeg: j0 } });
  return { transforms: stack };
}

// A smooth trajectory that sweeps every joint while staying inside its limits.
function trajectory(driveDeg) {
  const t = driveDeg * DEG;
  return {
    j0:  60 * Math.sin(t),                        // base sweeps -60..+60
    j1: -20 + 30 * Math.sin(t * 1.0 + 1.0),       // shoulder lift
    j2: -45 - 35 * Math.sin(t * 1.0 - 0.5),       // elbow bend (negative = down)
    j3:  20 + 40 * Math.sin(t * 1.3 + 2.1),       // wrist pitch
    j4: driveDeg * 2,                             // tool spins continuously
    grip: 8 + 18 * (0.5 + 0.5 * Math.sin(t * 2.0))  // gripper opening 8..26 mm
  };
}

export default {
  manifest: {
    schemaVersion: 1,
    parameters: {
      drive: {
        type: "number",
        label: "Trajectory",
        description: "Drives every joint along a smooth choreographed path.",
        unit: "deg",
        min: 0,
        max: 360,
        step: 1,
        default: 0
      },
      j0_override: { type: "number", label: "J0  base yaw",       unit: "deg", min: -150, max: 150, step: 1, default: 0 },
      j1_override: { type: "number", label: "J1  shoulder",       unit: "deg", min:  -90, max:  90, step: 1, default: 0 },
      j2_override: { type: "number", label: "J2  elbow",          unit: "deg", min: -120, max:  60, step: 1, default: 0 },
      j3_override: { type: "number", label: "J3  wrist pitch",    unit: "deg", min:  -90, max:  90, step: 1, default: 0 },
      j4_override: { type: "number", label: "J4  tool roll",      unit: "deg", min:  -180, max: 180, step: 1, default: 0 },
      use_overrides: { type: "boolean", label: "Manual joint control", default: false }
    },
    features: {
      base:           { ref: "#o1.1" },
      column:         { ref: "#o1.2" },
      upper_arm:      { ref: "#o1.3" },
      forearm:        { ref: "#o1.4" },
      wrist:          { ref: "#o1.5" },
      gripper_base:   { ref: "#o1.6" },
      gripper_left:   { ref: "#o1.7" },
      gripper_right:  { ref: "#o1.8" }
    },
    animations: {
      arm_cycle: { duration: 8, loop: true }
    }
  },

  update(ctx) {
    const { params, effects } = ctx;
    const drive = Number(params.drive) || 0;
    const auto = trajectory(drive);

    const useOverride = params.use_overrides === true;
    const j0 = useOverride ? Number(params.j0_override) || 0 : auto.j0;
    const j1 = useOverride ? Number(params.j1_override) || 0 : auto.j1;
    const j2 = useOverride ? Number(params.j2_override) || 0 : auto.j2;
    const j3 = useOverride ? Number(params.j3_override) || 0 : auto.j3;
    const j4 = useOverride ? Number(params.j4_override) || 0 : auto.j4;
    const gripOffset = useOverride ? 12 : auto.grip;  // half-spread per finger

    // ---- Per-frame palette: bright, saturated, easy to read against a dark bg ----
    effects.style("base",          { color: "#1f2937" });   // dark plinth as ground anchor
    effects.style("column",        { color: "#facc15" });   // bright yellow column
    effects.style("upper_arm",     { color: "#22d3ee" });   // electric cyan
    effects.style("forearm",       { color: "#a78bfa" });   // violet
    effects.style("wrist",         { color: "#f472b6" });   // hot pink
    effects.style("gripper_base",  { color: "#fb7185" });   // coral
    effects.style("gripper_left",  { color: "#84cc16", emissive: "#365314", emissiveIntensity: 0.2 });
    effects.style("gripper_right", { color: "#84cc16", emissive: "#365314", emissiveIntensity: 0.2 });

    // ---- Forward kinematics: each link adds joints upstream of itself ----
    effects.transform("column",       chain(j0));
    effects.transform("upper_arm",    chain(j0, j1));
    effects.transform("forearm",      chain(j0, j1, j2));
    effects.transform("wrist",        chain(j0, j1, j2, j3));
    effects.transform("gripper_base", chain(j0, j1, j2, j3, j4));

    // ---- Gripper fingers: open/close on Y (in tool frame) then ride the chain ----
    // Fingers are modeled at half_open = ~19 mm; sidecar moves them to gripOffset
    const baseHalfOpen = 19.0;
    const dY = gripOffset - baseHalfOpen;
    effects.transform("gripper_left", {
      transforms: [
        { translate: [0, +dY, 0] },
        { rotate: { axis: [1, 0, 0], origin: J4, angleDeg: j4 } },
        { rotate: { axis: [0, 1, 0], origin: J3, angleDeg: j3 } },
        { rotate: { axis: [0, 1, 0], origin: J2, angleDeg: j2 } },
        { rotate: { axis: [0, 1, 0], origin: J1, angleDeg: j1 } },
        { rotate: { axis: [0, 0, 1], origin: J0, angleDeg: j0 } }
      ]
    });
    effects.transform("gripper_right", {
      transforms: [
        { translate: [0, -dY, 0] },
        { rotate: { axis: [1, 0, 0], origin: J4, angleDeg: j4 } },
        { rotate: { axis: [0, 1, 0], origin: J3, angleDeg: j3 } },
        { rotate: { axis: [0, 1, 0], origin: J2, angleDeg: j2 } },
        { rotate: { axis: [0, 1, 0], origin: J1, angleDeg: j1 } },
        { rotate: { axis: [0, 0, 1], origin: J0, angleDeg: j0 } }
      ]
    });
  }
};
