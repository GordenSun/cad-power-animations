/* Folding chair sidecar — animated scissor mechanism.
 *
 * Universe coordinates (Z up). At zero pose, in the XZ plane:
 *   Leg A: bottom (+S, 0)            top (-S, H)
 *   Leg B: bottom (-S, 0)            top (+S, H)
 * with S = LEG_SPREAD_X, H = LEG_TOP_Z. Both legs intersect at (0, H/2)
 * — the default hinge.
 *
 * Animation parameters:
 *   - `fold`    (0..1) animated cycle, 0 = fully open, 1 = fully folded
 *   - `hinge_position` (0..1) slides the pivot point along each leg.
 *     0 = at the leg's bottom end, 0.5 = midpoint (the kinematically
 *     consistent X), 1 = at the leg's top end.
 *
 * Note: for hinge_position ≠ 0.5 the two legs no longer share a single
 * point — that visible separation is the point of the demo. It shows
 * that with the pivot off-centre the X-mechanism doesn't close cleanly,
 * which is exactly the trade-off you have to consider when designing a
 * scissor-fold.
 */

const LEG_SPREAD_X = 200.0;
const LEG_TOP_Z = 480.0;
const HINGE_DEFAULT_Z = LEG_TOP_Z * 0.5;
const SIDE_Y = 220.0;
const SEAT_THICK = 18.0;
const FOLD_MAX_DEG = 35.0;  // angle each leg rotates when fully folded

const DEG = Math.PI / 180;

function pivotForLeg(legKind, hp) {
  // Return (x, z) of the rotation pivot for this leg given hinge_position hp.
  // Leg A: (1-hp)*(+S, 0) + hp*(-S, H) = (S - 2*S*hp, H*hp)
  // Leg B: (1-hp)*(-S, 0) + hp*(+S, H) = (-S + 2*S*hp, H*hp)
  const z = LEG_TOP_Z * hp;
  if (legKind === "a") return [+LEG_SPREAD_X - 2 * LEG_SPREAD_X * hp, z];
  return [-LEG_SPREAD_X + 2 * LEG_SPREAD_X * hp, z];
}

export default {
  manifest: {
    schemaVersion: 1,
    parameters: {
      fold: {
        type: "number",
        label: "Fold",
        description: "0 = chair fully open; 1 = scissor closed.",
        min: 0, max: 1, step: 0.01, default: 0
      },
      hinge_position: {
        type: "number",
        label: "Hinge position",
        description: "Fraction along the leg where the pivot sits. 0.5 = symmetric scissor; anything else and the legs no longer share a pin so you can see the geometry break.",
        min: 0.1, max: 0.9, step: 0.01, default: 0.5
      }
    },
    features: {
      left_leg_a:     { ref: "#o1.1" },
      left_leg_b:     { ref: "#o1.2" },
      right_leg_a:    { ref: "#o1.3" },
      right_leg_b:    { ref: "#o1.4" },
      hinge_pin:      { ref: "#o1.5" },
      seat:           { ref: "#o1.6" },
      backrest:       { ref: "#o1.7" },
      ghost_envelope: { ref: "#o1.8" }
    },
    animations: {
      fold_cycle: { duration: 5, loop: true }
    }
  },

  update(ctx) {
    const { params, effects } = ctx;
    const fold = Math.min(Math.max(Number(params.fold) || 0, 0), 1);
    const hp = Math.min(Math.max(Number(params.hinge_position) ?? 0.5, 0.1), 0.9);
    // Symmetric pingpong-ish, so the animation cycles open-close-open
    const cyc = 0.5 - 0.5 * Math.cos(fold * Math.PI * 2);
    const angle = cyc * FOLD_MAX_DEG;

    // ---- Palette (vibrant, against the dark viewer background) ----
    effects.style("left_leg_a",     { color: "#22d3ee" });   // cyan front-pair
    effects.style("right_leg_a",    { color: "#22d3ee" });
    effects.style("left_leg_b",     { color: "#f472b6" });   // pink back-pair
    effects.style("right_leg_b",    { color: "#f472b6" });
    effects.style("hinge_pin",      { color: "#facc15", emissive: "#854d0e", emissiveIntensity: 0.3 });
    effects.style("seat",           { color: "#fb923c" });
    effects.style("backrest",       { color: "#a78bfa" });
    // Hide the ghost envelope by default - the visual scale math is finicky
    // for non-axis-centered geometry and the folding mechanism reads fine
    // on its own.
    effects.visible("ghost_envelope", false);

    // ---- Pivot for each leg (sides share Y) ----
    const [pivotAX, pivotAZ] = pivotForLeg("a", hp);
    const [pivotBX, pivotBZ] = pivotForLeg("b", hp);

    // ---- Rotate each leg around its hinge axis ----
    // Leg A is closing toward vertical → positive rotation around +Y.
    // Leg B closes by negative rotation.
    for (const sideY of [+SIDE_Y, -SIDE_Y]) {
      const tag = sideY > 0 ? "left" : "right";
      effects.transform(`${tag}_leg_a`, {
        rotate: { axis: [0, 1, 0], origin: [pivotAX, sideY, pivotAZ], angleDeg: +angle }
      });
      effects.transform(`${tag}_leg_b`, {
        rotate: { axis: [0, 1, 0], origin: [pivotBX, sideY, pivotBZ], angleDeg: -angle }
      });
    }

    // ---- Hinge pin: slide it visually along Z to match hinge_position ----
    const hingeZNow = LEG_TOP_Z * hp;
    effects.transform("hinge_pin", { translate: [0, 0, hingeZNow - HINGE_DEFAULT_Z] });

    // ---- Seat: follows the midpoint of the two leg tops (above hinge) ----
    // Compute Leg A top after rotation about its pivot.
    function rotatedTopZ(legKind, pivotX, pivotZ, angleDeg) {
      const top0 = legKind === "a"
        ? [-LEG_SPREAD_X, LEG_TOP_Z]
        : [+LEG_SPREAD_X, LEG_TOP_Z];
      const dx = top0[0] - pivotX;
      const dz = top0[1] - pivotZ;
      const a = angleDeg * DEG;
      // R_y(+a) applied to (dx, dz): (dx cos a + dz sin a, -dx sin a + dz cos a)
      const newDx =  dx * Math.cos(a) + dz * Math.sin(a);
      const newDz = -dx * Math.sin(a) + dz * Math.cos(a);
      return { x: pivotX + newDx, z: pivotZ + newDz };
    }
    const aTop = rotatedTopZ("a", pivotAX, pivotAZ, +angle);
    const bTop = rotatedTopZ("b", pivotBX, pivotBZ, -angle);
    const seatDz = ((aTop.z + bTop.z) / 2) - LEG_TOP_Z;
    const seatDx = (aTop.x + bTop.x) / 2;  // 0 when symmetric (hp == 0.5)
    effects.transform("seat", { translate: [seatDx, 0, seatDz] });
    effects.transform("backrest", { translate: [seatDx, 0, seatDz] });

  }
};
