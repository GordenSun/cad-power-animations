/* Spray bottle sidecar — pump cycle (press → spray → release → suck).
 *
 *   drive (0..360°, animated):
 *     0..90    press phase  — trigger swings in, piston shoves forward
 *     90..180  spray phase  — piston at TDC, spray cone visible
 *     180..270 release       — trigger returns, piston pulled back, dip
 *                              tube fills (liquid colour pulses to hint)
 *     270..360 dwell        — back to rest, ready for next press
 */

const PIVOT_X = 30.0 + 56.0 / 2 - 4;     // PUMP_X_CENTER + PUMP_LENGTH/2 - 4
const PIVOT_Z = (160.0 + 14.0 + 16.0) / 2 + 18.0 + 16.0 / 2;  // PUMP_Z (matches py)
const PISTON_STROKE = 28.0;
const PUMP_Z = (160.0 + 14.0 + 16.0) / 2 + 18.0 + 16.0 / 2;

// Trigger swings about Y at PIVOT. Pull angle is positive (more tilt).
const TRIGGER_REST_DEG = 10.0;
const TRIGGER_PULL_DEG = 28.0;     // additional rotation when pressed

const DEG = Math.PI / 180;

// Smooth ease-in-out for the press / release ramps.
function smooth(t) { return t * t * (3 - 2 * t); }

export default {
  manifest: {
    schemaVersion: 1,
    parameters: {
      drive: {
        type: "number",
        label: "Pump cycle",
        description: "One full cycle = press → spray → release → suck.",
        unit: "deg",
        min: 0, max: 360, step: 1, default: 0
      },
      fill_level: {
        type: "number",
        label: "Liquid fill",
        description: "Fraction of the bottle filled with liquid (visual only).",
        min: 0.05, max: 1.0, step: 0.01, default: 0.7
      }
    },
    features: {
      bottle:    { ref: "#o1.1" },
      liquid:    { ref: "#o1.2" },
      cap:       { ref: "#o1.3" },
      head:      { ref: "#o1.4" },
      dip_tube:  { ref: "#o1.5" },
      piston:    { ref: "#o1.6" },
      trigger:   { ref: "#o1.7" },
      spray:     { ref: "#o1.8" }
    },
    animations: {
      pump_cycle: { duration: 3.5, loop: true }
    }
  },

  update(ctx) {
    const { params, effects } = ctx;
    const drive = Number(params.drive) || 0;
    const fill  = Math.min(Math.max(Number(params.fill_level) || 0.7, 0.05), 1.0);

    // ---- Cycle phases ----
    let pumpFraction = 0;   // 0 = trigger at rest, 1 = trigger fully pulled
    let spraying = false;
    if (drive < 90) {
      pumpFraction = smooth(drive / 90);       // press
    } else if (drive < 180) {
      pumpFraction = 1.0;                       // held / spraying
      spraying = true;
    } else if (drive < 270) {
      pumpFraction = 1.0 - smooth((drive - 180) / 90);  // release
    } else {
      pumpFraction = 0;                          // idle dwell
    }
    // Spray fade-out begins near end of spray phase
    const sprayAlpha = spraying
      ? 0.85 - 0.5 * smooth(Math.max(0, (drive - 130) / 50))
      : 0;

    // ---- Palette ----
    effects.style("bottle",   { color: "#bae6fd", emissive: "#0c4a6e", emissiveIntensity: 0.1 });
    effects.style("liquid",   { color: "#22d3ee", emissive: "#0e7490",
                                emissiveIntensity: 0.35 + 0.1 * Math.sin(drive * 0.5 * DEG) });
    effects.style("cap",      { color: "#1f2937" });
    effects.style("head",     { color: "#1f2937" });
    effects.style("dip_tube", { color: "#94a3b8" });
    effects.style("piston",   { color: "#facc15" });
    effects.style("trigger",  { color: "#ef4444" });
    effects.style("spray",    {
      color: "#67e8f9",
      emissive: "#0ea5e9",
      emissiveIntensity: spraying ? 0.9 : 0
    });

    // ---- Trigger: rotate about Y at the pivot, swinging in by pumpFraction ----
    const triggerExtraDeg = pumpFraction * TRIGGER_PULL_DEG;
    effects.transform("trigger", {
      rotate: { axis: [0, 1, 0], origin: [PIVOT_X, 0, PIVOT_Z], angleDeg: -triggerExtraDeg }
    });

    // ---- Piston: translate forward (+X) along the pump axis as trigger pulls ----
    effects.transform("piston", {
      translate: [+pumpFraction * PISTON_STROKE, 0, 0]
    });

    // ---- Spray cone: visible only while pressing/holding ----
    effects.visible("spray", sprayAlpha > 0.02);

    // ---- Liquid: scale Z to match fill_level ----
    // The CAD models liquid at z = [0, LIQUID_H] with center at LIQUID_H/2.
    // Scaling about origin (z=0) shrinks the top toward 0, which keeps the
    // bottom flush with the bottle bottom.
    const baseLiquidH = 0.7;  // LIQUID_H/BOTTLE_H from python
    const scaleZ = Math.max(0.02, fill / baseLiquidH);
    effects.transform("liquid", {
      scale: [1, 1, scaleZ], origin: [0, 0, 0]
    });
  }
};
