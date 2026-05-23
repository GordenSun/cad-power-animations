/* Mechanism simulator sidecar — drives three classical mechanisms from a
 * single `drive` angle so the audience can compare the resulting motions.
 *
 *   - Crank-slider: rotary input (crank disc) → linear slider via a
 *     connecting rod. `crank_radius` parameter scales the pin orbit
 *     radius - the pin's visible position is moved by the sidecar so the
 *     stroke really changes (the rod and slider follow the updated
 *     crank-slider equation).
 *   - Cam follower: cam rotates, follower reciprocates. `cam_lift` scales
 *     the vertical amplitude of the follower without re-cutting the cam.
 *   - Gear pair: 24-tooth gear A drives 12-tooth gear B (2:1) -- both
 *     spin around their own Y axes, B in the opposite direction at 2× the
 *     speed.
 */

const CS_X = -700, CS_PIN_OFFSET_BASE = 50, CS_ROD_LEN = 220;
const CS_DISC_T = 18, CS_PIN_L = 30;
const CS_PIN_Y = CS_DISC_T / 2 + CS_PIN_L / 2;
const CS_SLIDER_X_ZERO = CS_X + CS_PIN_OFFSET_BASE + CS_ROD_LEN;

const CAM_X = 0;
const CAM_BASE_R = 50, CAM_LIFT_BASE = 22;
const FOLLOWER_LEN = 180;
const FOLLOWER_Z_ZERO = CAM_BASE_R + CAM_LIFT_BASE + FOLLOWER_LEN / 2;

const GA_R = 72, GB_R = 36, GEAR_RATIO = GA_R / GB_R;  // 2:1

const DEG = Math.PI / 180;

export default {
  manifest: {
    schemaVersion: 1,
    parameters: {
      drive: {
        type: "number",
        label: "Input angle",
        description: "Universal phase fed to all three mechanisms.",
        unit: "deg",
        min: 0, max: 720, step: 1, default: 0
      },
      crank_radius: {
        type: "number",
        label: "Crank radius (slider)",
        description: "Effective crank radius for the crank-slider. Larger = longer stroke.",
        unit: "mm",
        min: 10, max: 80, step: 1, default: 50
      },
      cam_lift: {
        type: "number",
        label: "Cam lift",
        description: "Extra rise that the cam imparts to the follower.",
        unit: "mm",
        min: 4, max: 40, step: 1, default: 22
      },
      gear_ratio_label: {
        type: "enum",
        label: "Gear ratio",
        description: "Visualization is fixed at 24-tooth driver vs 12-tooth driven (2:1).",
        options: [{ value: "2:1", label: "2:1 (fixed)" }],
        default: "2:1"
      }
    },
    features: {
      cs_guide:        { ref: "#o1.1" },
      cs_crank:        { ref: "#o1.2" },
      cs_pin:          { ref: "#o1.3" },
      cs_rod:          { ref: "#o1.4" },
      cs_slider:       { ref: "#o1.5" },
      follower_guide:  { ref: "#o1.6" },
      cam:             { ref: "#o1.7" },
      follower:        { ref: "#o1.8" },
      gear_a:          { ref: "#o1.9" },
      gear_b:          { ref: "#o1.10" },
      legend:          { ref: "#o1.11" }
    },
    animations: {
      run: { duration: 5, loop: true }
    }
  },

  update(ctx) {
    const { params, effects } = ctx;
    const theta = (Number(params.drive) || 0) * DEG;
    const crankR = Math.max(Number(params.crank_radius) || 50, 1);
    const lift   = Math.max(Number(params.cam_lift) || 22, 0);

    // ---- Palette: pop colours grouped per mechanism ----
    effects.style("cs_guide",       { color: "#1f2937" });
    effects.style("cs_crank",       { color: "#22d3ee" });
    effects.style("cs_pin",         { color: "#facc15", emissive: "#854d0e", emissiveIntensity: 0.3 });
    effects.style("cs_rod",         { color: "#fb923c" });
    effects.style("cs_slider",      { color: "#ef4444" });
    effects.style("follower_guide", { color: "#1f2937" });
    effects.style("cam",            { color: "#a78bfa", emissive: "#3b0764", emissiveIntensity: 0.2 });
    effects.style("follower",       { color: "#22d3ee" });
    effects.style("gear_a",         { color: "#84cc16", emissive: "#365314", emissiveIntensity: 0.15 });
    effects.style("gear_b",         { color: "#facc15", emissive: "#854d0e", emissiveIntensity: 0.2 });
    effects.style("legend",         { color: "#94a3b8" });

    // ============================================================
    // Crank-slider
    // ============================================================
    // The crank disc rotates around (CS_X, *, 0) about +Y.
    effects.transform("cs_crank", {
      rotate: { axis: [0, 1, 0], origin: [CS_X, 0, 0], angleDeg: -(params.drive || 0) }
    });
    // The pin sits at (CS_X + CS_PIN_OFFSET_BASE, CS_PIN_Y, 0) in CAD.
    // Move it so it ends up at:
    //   pin world = (CS_X + crankR * cos θ, CS_PIN_Y, crankR * sin θ)
    const pinX = CS_X + crankR * Math.cos(theta);
    const pinZ = crankR * Math.sin(theta);
    effects.transform("cs_pin", {
      translate: [pinX - (CS_X + CS_PIN_OFFSET_BASE), 0, pinZ]
    });
    // Crank-slider equation for the slider X position:
    //   x_slider = pinX + sqrt(ROD^2 - pinZ^2)
    const sqrtTerm = Math.sqrt(Math.max(CS_ROD_LEN * CS_ROD_LEN - pinZ * pinZ, 0));
    const sliderX = pinX + sqrtTerm;
    const sliderDx = sliderX - CS_SLIDER_X_ZERO;
    effects.transform("cs_slider", { translate: [sliderDx, 0, 0] });
    // Rod: small end at slider (X = sliderX), big end at pin (X = pinX, Z = pinZ).
    // CAD modelled the rod centred at ((big_x0 + small_x0)/2, *, 0) with its
    // long axis along +X. We pivot around the small end and translate the
    // small end to sliderX.
    const smallEndX0 = CS_X + CS_PIN_OFFSET_BASE + CS_ROD_LEN;
    const gammaRad = Math.asin(Math.max(-1, Math.min(1, pinZ / CS_ROD_LEN)));
    // After rotation about the small end by +γ around Y, the rod's big end
    // moves to (small - L cos γ, L sin γ) relative to small. We need the
    // big end at (pinX, pinZ). With sliderX = pinX + sqrt(...), the geometry
    // matches automatically. The rotation angle is +γ.
    effects.transform("cs_rod", {
      transforms: [
        { rotate: { axis: [0, 1, 0], origin: [smallEndX0, 0, 0], angleDeg: -gammaRad / DEG } },
        { translate: [sliderDx, 0, 0] }
      ]
    });

    // ============================================================
    // Cam follower
    // ============================================================
    // Cam rotates about (CAM_X, *, 0) at drive rate.
    effects.transform("cam", {
      rotate: { axis: [0, 1, 0], origin: [CAM_X, 0, 0], angleDeg: -(params.drive || 0) }
    });
    // Follower height follows the cam lobe profile. The CAD has a single
    // lobe on +X side; as the cam rotates, the rim radius at the +Z
    // direction varies between base and base + (lift_visible). Use a
    // smoothed cosine: lift = lift * (0.5 + 0.5 * cos(θ - π)) so the lobe
    // hits +Z at θ = 180° (half a turn after start).
    // For simplicity, lift effect: max when cam's bump points up.
    const camAngle = theta;  // cam's own rotation
    // Bump initially at +X; after rotation by camAngle, bump direction angle = camAngle
    // Height contribution depends on angle from +Z (vertical). Use cos.
    const liftFraction = Math.max(0, Math.cos(camAngle - Math.PI / 2));
    const followerDz = -lift * (1 - liftFraction);   // negative = dropped; zero at top
    effects.transform("follower", { translate: [0, 0, followerDz] });

    // ============================================================
    // Gear pair (24 vs 12 teeth → B turns 2× speed in opposite direction)
    // ============================================================
    const driveDeg = Number(params.drive) || 0;
    const GA_X = 700 - GA_R - 4;                   // matches python
    const GB_X = GA_X + GA_R + GB_R + 1.5;
    effects.transform("gear_a", {
      rotate: { axis: [0, 1, 0], origin: [GA_X, 0, 0], angleDeg: -driveDeg }
    });
    effects.transform("gear_b", {
      rotate: { axis: [0, 1, 0], origin: [GB_X, 0, 0], angleDeg: +driveDeg * GEAR_RATIO }
    });
  }
};
