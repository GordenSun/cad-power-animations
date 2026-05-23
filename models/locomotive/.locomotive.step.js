/* Steam locomotive drivetrain sidecar.
 *
 *   crank (0..360 deg, animated) is the universal phase of every drive
 *   wheel (they are mechanically tied via the side rod).
 *
 *   Drive wheels:  rotate around their hub Y-axis by `-crank` deg
 *   Crank pins:    sit on their wheel, so they ride the same rotation
 *   Side rod:      stays horizontal, translates in a circle of radius
 *                  CRANK_R (dx = R(cos t - 1), dz = R sin t)
 *   Main rod:      big end orbits with the main wheel crank pin, small
 *                  end stays on the piston axis - rod tilts in XZ plane
 *   Piston:        slides along X by the crank-slider equation
 *
 * Geometry constants below must match locomotive.py.
 */

const WHEEL_R = 380;
const CRANK_R = 130;
const WHEEL_X = [-900, 0, 900];
const MAIN_WHEEL_X = 900;
const TRACK = 720;
const WHEEL_W = 80;
const CYLINDER_CENTER_X = MAIN_WHEEL_X + 850;
const CYLINDER_LENGTH = 460;
const PISTON_LENGTH = 60;
// Geometry-derived constants (must match locomotive.py)
const MAIN_ROD_LENGTH =
  (CYLINDER_CENTER_X - PISTON_LENGTH / 2) - (MAIN_WHEEL_X + CRANK_R);
const WHEEL_Z = WHEEL_R;
// y_center (outboard face) used for crank pin / rod / piston Y placement
const Y_LEFT  = +TRACK / 2 + (WHEEL_W / 2 + 25);
const Y_RIGHT = -TRACK / 2 - (WHEEL_W / 2 + 25);

const DEG = Math.PI / 180;

// Initial X position of the piston at crank=0 (used to compute slide delta)
const PISTON_X_AT_ZERO =
  MAIN_WHEEL_X + CRANK_R + Math.sqrt(MAIN_ROD_LENGTH * MAIN_ROD_LENGTH);

// Static crosshead position the locomotive.py modeled the piston at
// (we put the piston at CYLINDER_CENTER_X in the source)
const PISTON_MODEL_X = CYLINDER_CENTER_X;

function pistonState(crankDeg, leftSide) {
  // Same crank angle on both sides for simplicity (in reality offset by 90).
  const t = crankDeg * DEG;
  const sin = Math.sin(t);
  const cos = Math.cos(t);
  // Crank pin world position (relative to wheel center) at angle t:
  //   pin = (R*cos, 0, R*sin)
  // At t=0 the pin sits forward (+X), so source models the rod from
  //   big_end = (MAIN_WHEEL_X + R, y, WHEEL_Z)  to  small_end = (MAIN_WHEEL_X + R + L, y, WHEEL_Z)
  // Piston position (crank-slider):
  const pinX = MAIN_WHEEL_X + CRANK_R * cos;
  const pinZ = WHEEL_Z + CRANK_R * sin;
  const sqrtTerm = Math.sqrt(
    Math.max(MAIN_ROD_LENGTH * MAIN_ROD_LENGTH - (CRANK_R * sin) ** 2, 0)
  );
  const pistonX = pinX + sqrtTerm;
  const pistonDx = pistonX - PISTON_X_AT_ZERO;
  // Main rod tilt angle (around Y), positive when pin is up (+Z)
  // Big end goes from (R, 0) to (R*cos, R*sin) relative to MAIN_WHEEL_X.
  // Rod tilt about its small end (piston pin) so that big end lands on
  // the crank pin:
  //   small_end_world = (pistonX, y, WHEEL_Z)
  //   big_end_world   = (pinX,    y, pinZ)
  // Rod vector = big - small = (pinX - pistonX, 0, pinZ - WHEEL_Z)
  // = (-sqrtTerm, 0, R*sin)
  // Tilt: we model the rod at zero tilt (horizontal); to land big end on the
  // crank pin via rotation about the small end, we need angle gamma where
  // the rod end (originally at (-rod_length, 0, 0)) maps to
  // (-sqrt, 0, R*sin). That gives sin(gamma) = -R*sin / rod_length.
  // We then rotate around small end (which sits at piston axis Z = WHEEL_Z).
  const gamma = -Math.asin((CRANK_R * sin) / MAIN_ROD_LENGTH);
  return { pistonDx, gamma };
}

export default {
  manifest: {
    schemaVersion: 1,
    parameters: {
      crank: {
        type: "number",
        label: "Drive crank",
        description: "Universal phase of all drive wheels. Side rod and main rod follow.",
        unit: "deg",
        min: 0,
        max: 720,
        step: 1,
        default: 0
      }
    },
    features: {
      frame:       { ref: "#o1.1" },
      boiler:      { ref: "#o1.2" },
      cab:         { ref: "#o1.3" },
      cowcatcher:  { ref: "#o1.4" },
      wheel_rl:    { ref: "#o1.5" },
      wheel_ml:    { ref: "#o1.6" },
      wheel_fl:    { ref: "#o1.7" },
      wheel_rr:    { ref: "#o1.8" },
      wheel_mr:    { ref: "#o1.9" },
      wheel_fr:    { ref: "#o1.10" },
      pin_l_1:     { ref: "#o1.11" },
      pin_l_2:     { ref: "#o1.12" },
      pin_l_3:     { ref: "#o1.13" },
      pin_r_1:     { ref: "#o1.14" },
      pin_r_2:     { ref: "#o1.15" },
      pin_r_3:     { ref: "#o1.16" },
      side_rod_l:  { ref: "#o1.17" },
      side_rod_r:  { ref: "#o1.18" },
      main_rod_l:  { ref: "#o1.19" },
      main_rod_r:  { ref: "#o1.20" },
      cylinder_l:  { ref: "#o1.21" },
      cylinder_r:  { ref: "#o1.22" },
      piston_l:    { ref: "#o1.23" },
      piston_r:    { ref: "#o1.24" }
    },
    animations: {
      drive: { duration: 4, loop: true }
    }
  },

  update(ctx) {
    const { params, effects } = ctx;
    const crank = Number(params.crank) || 0;
    const t = crank * DEG;
    const cos = Math.cos(t);
    const sin = Math.sin(t);

    // ---- Bright palette so each functional group reads at a glance ----
    effects.style("frame",      { color: "#1f2937" });   // dark plinth
    effects.style("boiler",     { color: "#16a34a" });   // British racing green
    effects.style("cab",        { color: "#dc2626" });   // signal red cab
    effects.style("cowcatcher", { color: "#facc15" });   // yellow pilot
    for (const w of ["wheel_rl","wheel_ml","wheel_fl","wheel_rr","wheel_mr","wheel_fr"]) {
      effects.style(w, { color: "#ef4444", emissive: "#7f1d1d", emissiveIntensity: 0.15 });
    }
    for (const p of ["pin_l_1","pin_l_2","pin_l_3","pin_r_1","pin_r_2","pin_r_3"]) {
      effects.style(p, { color: "#facc15" });
    }
    effects.style("side_rod_l",  { color: "#fbbf24", emissive: "#7c2d12", emissiveIntensity: 0.18 });
    effects.style("side_rod_r",  { color: "#fbbf24", emissive: "#7c2d12", emissiveIntensity: 0.18 });
    effects.style("main_rod_l",  { color: "#22d3ee" });
    effects.style("main_rod_r",  { color: "#22d3ee" });
    effects.style("cylinder_l",  { color: "#a78bfa" });
    effects.style("cylinder_r",  { color: "#a78bfa" });
    effects.style("piston_l",    { color: "#f472b6", emissive: "#831843", emissiveIntensity: 0.2 });
    effects.style("piston_r",    { color: "#f472b6", emissive: "#831843", emissiveIntensity: 0.2 });

    // ---- Wheels + crank pins: all rotate by -crank around their hub Y axis ----
    function wheelRot(x) {
      return { rotate: { axis: [0, 1, 0], origin: [x, 0, WHEEL_Z], angleDeg: -crank } };
    }
    const wheelMap = { wheel_rl:-900, wheel_ml:0, wheel_fl:900,
                       wheel_rr:-900, wheel_mr:0, wheel_fr:900 };
    for (const [w, x] of Object.entries(wheelMap)) {
      effects.transform(w, wheelRot(x));
    }
    const pinX = { pin_l_1:-900, pin_l_2:0, pin_l_3:900,
                   pin_r_1:-900, pin_r_2:0, pin_r_3:900 };
    for (const [p, x] of Object.entries(pinX)) {
      effects.transform(p, wheelRot(x));
    }

    // ---- Side rods: orbit in a circle of radius CRANK_R, no rotation ----
    // At crank=0 each pin is at (x + CRANK_R, y, WHEEL_Z). At general angle
    // the pin is at (x + CRANK_R cos, y, WHEEL_Z + CRANK_R sin), so the rod
    // translates by (CRANK_R*(cos-1), 0, CRANK_R*sin).
    const rodTranslate = [CRANK_R * (cos - 1), 0, CRANK_R * sin];
    effects.transform("side_rod_l", { translate: rodTranslate });
    effects.transform("side_rod_r", { translate: rodTranslate });

    // ---- Main rods: tilt + translate so they connect piston to crank pin ----
    // Source places the rod horizontal from (MAIN_WHEEL_X + CRANK_R) (big end)
    // to (MAIN_WHEEL_X + CRANK_R + ROD_L) (small end). We pivot the small
    // end so the big end follows the crank pin, then shift the small end to
    // match the piston's current X.
    const stateL = pistonState(crank, true);
    const smallEndZeroX = MAIN_WHEEL_X + CRANK_R + MAIN_ROD_LENGTH;
    function mainRodSpec(y) {
      return {
        transforms: [
          { rotate: { axis: [0, 1, 0], origin: [smallEndZeroX, y, WHEEL_Z], angleDeg: stateL.gamma * 180 / Math.PI } },
          { translate: [stateL.pistonDx, 0, 0] }
        ]
      };
    }
    effects.transform("main_rod_l", mainRodSpec(Y_LEFT));
    effects.transform("main_rod_r", mainRodSpec(Y_RIGHT));

    // ---- Pistons: slide along X by the same crank-slider delta ----
    effects.transform("piston_l", { translate: [stateL.pistonDx, 0, 0] });
    effects.transform("piston_r", { translate: [stateL.pistonDx, 0, 0] });
  }
};
