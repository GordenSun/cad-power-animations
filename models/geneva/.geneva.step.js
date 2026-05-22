/* Geneva drive sidecar.
 *
 * 4-slot Geneva mechanism. The driver (carrying the pin + lock disc)
 * rotates continuously around the driver center; the driven wheel
 * rotates intermittently in 90 deg steps.
 *
 * Kinematics for a 4-slot Geneva with R_pin (driver pin radius) and
 * center distance C = R_pin * sqrt(2):
 *
 *   - Engagement window: pin in [-45 deg, +45 deg] relative to the
 *     driver -> driven center line (X axis here).
 *   - During engagement, the slot direction (angle from driven centre)
 *     equals  atan2(R_pin*sin psi, R_pin*cos psi - C),
 *     swept continuously CW, giving exactly 90 deg of driven motion.
 *   - Between engagements, the lock disc holds the driven wheel still.
 */

const N_SLOTS = 4;
const DRIVEN_RADIUS = 110.0;
const C = DRIVEN_RADIUS * Math.sqrt(2);       // center distance
const R_PIN = Math.sqrt(C * C - DRIVEN_RADIUS * DRIVEN_RADIUS); // ≈ R_driven

const DRIVEN_CENTER = [C, 0, 0];

const DEG = Math.PI / 180;

function genevaSlotAngle(psiRad) {
  const dx = R_PIN * Math.cos(psiRad) - C;
  const dz = R_PIN * Math.sin(psiRad);
  return Math.atan2(dz, dx);
}

const SLOT_ANGLE_AT_ENTRY = -3 * Math.PI / 4; // -135 deg

function genevaDeltaDeg(offsetDeg) {
  const psi = offsetDeg * DEG;
  let slotAngle = genevaSlotAngle(psi);
  // Continuous CW path: keep slotAngle in [-2π, 0)
  if (slotAngle > 0) slotAngle -= 2 * Math.PI;
  return (slotAngle - SLOT_ANGLE_AT_ENTRY) / DEG; // 0 → -90
}

function drivenAngleDeg(driveDeg) {
  // N = number of the current engagement cycle (0, 1, 2, ...).
  // Engagement #N is centred at driveDeg = N * 360.
  const N = Math.round(driveDeg / 360);
  const offset = driveDeg - N * 360;        // (-180, 180]
  const baselineDeg = -90 * N;
  if (offset > -45 && offset < 45) {
    return baselineDeg + genevaDeltaDeg(offset);
  }
  if (offset >= 45) return baselineDeg - 90;
  return baselineDeg;                       // offset <= -45
}

export default {
  manifest: {
    schemaVersion: 1,
    parameters: {
      drive: {
        type: "number",
        label: "Driver angle",
        description: "Continuous rotation of the driver (pin + lock disc). The driven wheel snaps 90 deg per driver revolution.",
        unit: "deg",
        min: 0,
        max: 1440,
        step: 1,
        default: 0
      }
    },
    features: {
      base:        { ref: "#o1.1" },
      driver_disc: { ref: "#o1.2" },
      lock_disc:   { ref: "#o1.3" },
      pin:         { ref: "#o1.4" },
      driven:      { ref: "#o1.5" }
    },
    animations: {
      geneva_cycle: { duration: 8, loop: true }
    }
  },

  update(ctx) {
    const { params, effects } = ctx;
    const driveDeg = Number(params.drive) || 0;

    // ---- Bright styling ----
    effects.style("base",        { color: "#312e81" });           // indigo back plate
    effects.style("driver_disc", { color: "#fb923c", emissive: "#7c2d12", emissiveIntensity: 0.3 }); // orange
    effects.style("lock_disc",   { color: "#ef4444", emissive: "#7f1d1d", emissiveIntensity: 0.25 }); // red
    effects.style("pin",         { color: "#fde047", emissive: "#a16207", emissiveIntensity: 0.6 });  // bright yellow
    effects.style("driven",      { color: "#22d3ee", emissive: "#0e7490", emissiveIntensity: 0.35 }); // cyan

    // ---- Kinematics ----
    const driverSpin = {
      rotate: { axis: [0, 1, 0], origin: [0, 0, 0], angleDeg: driveDeg }
    };
    effects.transform("driver_disc", driverSpin);
    effects.transform("lock_disc",   driverSpin);
    effects.transform("pin",         driverSpin);

    const drivenDeg = drivenAngleDeg(driveDeg);
    effects.transform("driven", {
      rotate: { axis: [0, 1, 0], origin: DRIVEN_CENTER, angleDeg: drivenDeg }
    });
  }
};
