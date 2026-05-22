/* F1 car STEP module sidecar.
 *
 * Drives the "power principle" animation:
 *   crank rotation -> piston reciprocation + connecting-rod articulation
 *   crank -> clutch -> drive shaft -> differential -> rear axle -> wheels.
 *
 * The only required animated parameter is `drive`, the engine crank angle
 * in degrees. All wheel, axle and rod motions are derived from it.
 *
 * Geometry constants below mirror the build123d source in f1_car.py.
 * Keep them in sync when changing engine dimensions.
 */

// ---- Geometry constants (must match f1_car.py) ----
const CRANK_R = 60;          // half-stroke (mm)
const ROD_LENGTH = 260;      // connecting rod length (mm)
const CRANK_AXIS_Z = 190;    // ENGINE_BLOCK_Z - HEIGHT/2 + 80 = 290 - 180 + 80
const PISTON_BOTTOM_Z = CRANK_AXIS_Z + CRANK_R + ROD_LENGTH; // 510 (at TDC)
const ENGINE_CENTER_X = -1050;
const CYL_SPACING = 180;
const NUM_CYLINDERS = 4;
const CYL_X = Array.from({ length: NUM_CYLINDERS },
  (_, i) => ENGINE_CENTER_X + (-((NUM_CYLINDERS - 1) / 2) + i) * CYL_SPACING);
// Inline-4 firing order 1-3-4-2: pistons 1 & 4 share TDC, 2 & 3 share BDC.
const PHASES_DEG = [0, 180, 180, 0];

const WHEELBASE = 3600;
const WHEEL_RADIUS = 360;
const REAR_AXLE_X = -WHEELBASE / 2;
const FRONT_AXLE_X = WHEELBASE / 2;

// ---- Helpers ----
const DEG = Math.PI / 180;

function pistonState(crankAngleDeg, phaseDeg) {
  const angle = (crankAngleDeg + phaseDeg) * DEG;
  const sinT = Math.sin(angle);
  const cosT = Math.cos(angle);
  const rodCos = Math.sqrt(Math.max(ROD_LENGTH * ROD_LENGTH - (CRANK_R * sinT) ** 2, 0));
  // Piston bottom Z and the corresponding rod tilt angle.
  const pistonZ = CRANK_AXIS_Z + CRANK_R * cosT + rodCos;
  const zOffset = pistonZ - PISTON_BOTTOM_Z;  // <= 0
  // Rod tilt about the small-end pivot (around +X axis).
  // gamma so that rod big-end lands on the crank pin.
  const gamma = Math.asin((CRANK_R * sinT) / ROD_LENGTH);
  return { zOffset, gamma };
}

export default {
  manifest: {
    schemaVersion: 1,
    parameters: {
      drive: {
        type: "number",
        label: "Crank angle",
        description: "Engine crank angle. Two full revolutions = one four-stroke cycle.",
        unit: "deg",
        min: 0,
        max: 720,
        step: 1,
        default: 0
      },
      gear_ratio: {
        type: "number",
        label: "Final drive ratio",
        description: "Crank turns per wheel turn. Real F1 is ~10:1 in low gear; lowered here for visible wheel spin.",
        min: 1,
        max: 8,
        step: 0.1,
        default: 3.5
      },
      show_sleeves: {
        type: "boolean",
        label: "Show cylinder sleeves",
        description: "Toggle the cut-away cylinder bores around each piston.",
        default: true
      },
      highlight_drivetrain: {
        type: "boolean",
        label: "Highlight drivetrain",
        description: "Tint the crank / drive shaft / differential / rear axle so the power path stands out.",
        default: true
      }
    },
    features: {
      monocoque:   { ref: "#o1.1" },
      floor:       { ref: "#o1.2" },
      sidepod_l:   { ref: "#o1.3" },
      sidepod_r:   { ref: "#o1.4" },
      nose:        { ref: "#o1.5" },
      front_wing:  { ref: "#o1.6" },
      rear_wing:   { ref: "#o1.7" },
      halo:        { ref: "#o1.8" },
      helmet:      { ref: "#o1.9" },
      engine:      { ref: "#o1.10" },
      sleeve_1:    { ref: "#o1.11" },
      sleeve_2:    { ref: "#o1.12" },
      sleeve_3:    { ref: "#o1.13" },
      sleeve_4:    { ref: "#o1.14" },
      piston_1:    { ref: "#o1.15" },
      piston_2:    { ref: "#o1.16" },
      piston_3:    { ref: "#o1.17" },
      piston_4:    { ref: "#o1.18" },
      rod_1:       { ref: "#o1.19" },
      rod_2:       { ref: "#o1.20" },
      rod_3:       { ref: "#o1.21" },
      rod_4:       { ref: "#o1.22" },
      crankshaft:  { ref: "#o1.23" },
      clutch:      { ref: "#o1.24" },
      drive_shaft: { ref: "#o1.25" },
      differential:{ ref: "#o1.26" },
      front_axle:  { ref: "#o1.27" },
      rear_axle:   { ref: "#o1.28" },
      wheel_fl:    { ref: "#o1.29" },
      wheel_fr:    { ref: "#o1.30" },
      wheel_rl:    { ref: "#o1.31" },
      wheel_rr:    { ref: "#o1.32" }
    },
    animations: {
      engine_cycle: { duration: 4, loop: true }
    }
  },

  /**
   * Per-frame update: read params.drive and apply transforms to each animated
   * feature. Idempotent - the effects API is reset before each call.
   * Styling is set here (not in setup) because the viewer resets per-part
   * effects between updates.
   */
  update(ctx) {
    const { params, effects } = ctx;
    const drive = Number(params.drive) || 0;

    // ---- Per-frame styling (so the power path reads at a glance) ----
    const PISTON_COLOR = "#ef4444";   // hot red
    const ROD_COLOR    = "#94a3b8";   // steel
    const CRANK_COLOR  = "#fbbf24";   // brass / amber
    const DIFF_COLOR   = "#f59e0b";   // orange
    const WHEEL_COLOR  = "#1f2937";   // tyre slate
    for (let i = 1; i <= 4; i += 1) {
      effects.style(`piston_${i}`, { color: PISTON_COLOR, emissive: "#7f1d1d", emissiveIntensity: 0.2 });
      effects.style(`rod_${i}`,    { color: ROD_COLOR });
    }
    if (params.highlight_drivetrain !== false) {
      effects.style("crankshaft",   { color: CRANK_COLOR });
      effects.style("clutch",       { color: CRANK_COLOR });
      effects.style("drive_shaft",  { color: CRANK_COLOR });
      effects.style("differential", { color: DIFF_COLOR });
      effects.style("rear_axle",    { color: CRANK_COLOR });
    }
    for (const w of ["wheel_fl", "wheel_fr", "wheel_rl", "wheel_rr"]) {
      effects.style(w, { color: WHEEL_COLOR });
    }

    // ---- Pistons + connecting rods ----
    for (let i = 0; i < NUM_CYLINDERS; i += 1) {
      const { zOffset, gamma } = pistonState(drive, PHASES_DEG[i]);
      effects.transform(`piston_${i + 1}`, { translate: [0, 0, zOffset] });
      effects.transform(`rod_${i + 1}`, {
        transforms: [
          {
            rotate: {
              axis: [1, 0, 0],
              origin: [CYL_X[i], 0, PISTON_BOTTOM_Z],
              angleRad: gamma
            }
          },
          { translate: [0, 0, zOffset] }
        ]
      });
    }

    // ---- Crankshaft / clutch / drive shaft (rigid 1:1 with crank) ----
    const crankRotation = {
      rotate: {
        axis: [1, 0, 0],
        origin: [0, 0, CRANK_AXIS_Z],
        angleDeg: -drive
      }
    };
    effects.transform("crankshaft", crankRotation);
    effects.transform("clutch", crankRotation);
    effects.transform("drive_shaft", crankRotation);
    effects.transform("differential", crankRotation);

    // ---- Rear axle / wheels (driven via final drive) ----
    const ratio = Math.max(Number(params.gear_ratio) || 3.5, 0.1);
    const wheelAngleDeg = -drive / ratio;
    const rearSpin = {
      rotate: { axis: [0, 1, 0], origin: [REAR_AXLE_X, 0, WHEEL_RADIUS], angleDeg: wheelAngleDeg }
    };
    effects.transform("rear_axle", rearSpin);
    effects.transform("wheel_rl", rearSpin);
    effects.transform("wheel_rr", rearSpin);

    // Free-rolling front wheels (purely cosmetic on this RWD car).
    const frontSpin = {
      rotate: { axis: [0, 1, 0], origin: [FRONT_AXLE_X, 0, WHEEL_RADIUS], angleDeg: wheelAngleDeg }
    };
    effects.transform("front_axle", frontSpin);
    effects.transform("wheel_fl", frontSpin);
    effects.transform("wheel_fr", frontSpin);

    // ---- Sleeve visibility toggle ----
    const showSleeves = params.show_sleeves !== false;
    for (let i = 1; i <= NUM_CYLINDERS; i += 1) {
      effects.visible(`sleeve_${i}`, showSleeves);
    }
  }
};
