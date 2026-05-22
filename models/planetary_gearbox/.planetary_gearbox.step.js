/* Planetary gearbox STEP module sidecar.
 *
 * Kinematics (sun input, ring fixed, carrier output):
 *   ω_carrier         = ω_sun * Zs / (Zs + Zr)
 *   ω_planet_world    = -ω_sun * Zs / Zp + ω_carrier * (1 + Zs / Zp)
 *
 * Constants below must match planetary_gearbox.py.
 */

const SUN_TEETH = 12;
const PLANET_TEETH = 18;
const RING_TEETH = SUN_TEETH + 2 * PLANET_TEETH;       // 48
const MODULE = 8.0;
const SUN_R = SUN_TEETH * MODULE / 2;
const PLANET_R = PLANET_TEETH * MODULE / 2;
const CARRIER_RADIUS = SUN_R + PLANET_R;               // 120

const DEG = Math.PI / 180;

// Derived gear ratios
const CARRIER_RATIO = SUN_TEETH / (SUN_TEETH + RING_TEETH);          // 0.2
const PLANET_SELF_RATIO_ON_CARRIER = -(SUN_TEETH / PLANET_TEETH);    // -2/3 in carrier frame
const PLANET_WORLD_RATIO =
  PLANET_SELF_RATIO_ON_CARRIER + CARRIER_RATIO;                      // -2/3 + 0.2 = -7/15
// (the "+ CARRIER_RATIO" term is because the carrier itself rotates and
// the planet rides along, so the planet's body has both spin and revolution)

// Initial planet centers in world space (used as rotation pivots for self-spin)
const PLANET_CENTERS = [0, 1, 2].map(i => {
  const theta = i * (2 * Math.PI / 3);
  return [CARRIER_RADIUS * Math.cos(theta), 0, CARRIER_RADIUS * Math.sin(theta)];
});

export default {
  manifest: {
    schemaVersion: 1,
    parameters: {
      drive: {
        type: "number",
        label: "Sun input angle",
        description: "Drive angle of the sun (input). Planets and carrier follow by the standard planetary kinematics.",
        unit: "deg",
        min: 0,
        max: 1080,
        step: 1,
        default: 0
      }
    },
    features: {
      ring:         { ref: "#o1.1" },
      sun:          { ref: "#o1.2" },
      planet_1:     { ref: "#o1.3" },
      planet_2:     { ref: "#o1.4" },
      planet_3:     { ref: "#o1.5" },
      carrier:      { ref: "#o1.6" },
      input_shaft:  { ref: "#o1.7" },
      output_shaft: { ref: "#o1.8" }
    },
    animations: {
      gear_cycle: { duration: 6, loop: true }
    }
  },

  update(ctx) {
    const { params, effects } = ctx;
    const sun = Number(params.drive) || 0;

    // ---- bright styling (re-applied every frame) ----
    effects.style("ring",      { color: "#22d3ee", emissive: "#0e7490", emissiveIntensity: 0.25 }); // cyan stator
    effects.style("sun",       { color: "#fde047", emissive: "#a16207", emissiveIntensity: 0.45 }); // yellow sun
    effects.style("planet_1",  { color: "#fb923c", emissive: "#9a3412", emissiveIntensity: 0.3  }); // orange
    effects.style("planet_2",  { color: "#34d399", emissive: "#065f46", emissiveIntensity: 0.3  }); // mint
    effects.style("planet_3",  { color: "#f472b6", emissive: "#831843", emissiveIntensity: 0.3  }); // pink
    effects.style("carrier",   { color: "#a78bfa", emissive: "#4c1d95", emissiveIntensity: 0.2  }); // violet
    effects.style("input_shaft",  { color: "#fbbf24" });
    effects.style("output_shaft", { color: "#a78bfa" });

    // ---- kinematics ----
    const sunDeg = sun;                                   // sun rotation
    const carrierDeg = sun * CARRIER_RATIO;               // carrier rotation
    const planetWorldDeg = sun * PLANET_WORLD_RATIO;      // planet spin in world frame

    // Sun + input shaft spin together around the global Y axis at origin
    const sunSpin = {
      rotate: { axis: [0, 1, 0], origin: [0, 0, 0], angleDeg: sunDeg }
    };
    effects.transform("sun", sunSpin);
    effects.transform("input_shaft", sunSpin);

    // Carrier + output shaft revolve around the global axis (sun centerline)
    const carrierSpin = {
      rotate: { axis: [0, 1, 0], origin: [0, 0, 0], angleDeg: carrierDeg }
    };
    effects.transform("carrier", carrierSpin);
    effects.transform("output_shaft", carrierSpin);

    // Each planet: spin around its own initial center, then revolve with carrier
    for (let i = 0; i < 3; i += 1) {
      effects.transform(`planet_${i + 1}`, {
        transforms: [
          { rotate: { axis: [0, 1, 0], origin: PLANET_CENTERS[i], angleDeg: planetWorldDeg } },
          { rotate: { axis: [0, 1, 0], origin: [0, 0, 0], angleDeg: carrierDeg } }
        ]
      });
    }
  }
};
