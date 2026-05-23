/* Solar system sidecar.
 *
 * `time` (deg, animated 0..360) is the angular position of Earth around
 * the Sun. Every other planet's orbit is scaled relative to Earth's by
 * a fixed ratio (roughly Kepler-ish, but tuned so the inner planets
 * obviously zip while Saturn lumbers along).
 *
 * Each planet is modeled at its (orbit_radius, 0, 0) zero-pose; we then
 * rotate it around the Sun (Z axis at origin). The Moon is special: it
 * orbits Earth, so its kinematic chain is
 *   1. rotate around Earth's INITIAL position by moon_angle
 *   2. rotate around Sun by earth_angle
 * which the viewer composes via the `transforms` array.
 */

const EARTH_ORBIT = 320;

// Orbital speed multipliers (Earth = 1). Inflated for visual rhythm.
const SPEED = {
  mercury: 4.15,
  venus:   1.62,
  earth:   1.0,
  moon:   13.4,   // moons-per-earth-year
  mars:    0.53,
  jupiter: 0.30,  // really 0.084 but slowed too much for video
  saturn:  0.18   // really 0.034
};

// Self-spin multipliers (Earth = 1). Visual only, not physical.
const SPIN = {
  mercury: 6,
  venus:   4,
  earth:   8,
  moon:    8,
  mars:    7,
  jupiter: 18,
  saturn:  16
};

export default {
  manifest: {
    schemaVersion: 1,
    parameters: {
      time: {
        type: "number",
        label: "Earth angle",
        description: "Orbital angle of Earth. All other planets scale from it.",
        unit: "deg",
        min: 0,
        max: 360,
        step: 1,
        default: 0
      },
      show_orbits: {
        type: "boolean",
        label: "Show orbits",
        default: true
      },
      sun_pulse: {
        type: "boolean",
        label: "Sun corona pulse",
        default: true
      }
    },
    features: {
      sun:           { ref: "#o1.1" },
      orbit_mercury: { ref: "#o1.2" },
      orbit_venus:   { ref: "#o1.3" },
      orbit_earth:   { ref: "#o1.4" },
      orbit_mars:    { ref: "#o1.5" },
      orbit_jupiter: { ref: "#o1.6" },
      orbit_saturn:  { ref: "#o1.7" },
      mercury:       { ref: "#o1.8" },
      venus:         { ref: "#o1.9" },
      earth:         { ref: "#o1.10" },
      moon:          { ref: "#o1.11" },
      mars:          { ref: "#o1.12" },
      jupiter:       { ref: "#o1.13" },
      saturn:        { ref: "#o1.14" }
    },
    animations: {
      orbit: { duration: 10, loop: true }
    }
  },

  update(ctx) {
    const { params, effects } = ctx;
    const t = Number(params.time) || 0;
    const showOrbits = params.show_orbits !== false;

    // ---- Bright planetary palette ----
    const sunEmissive = params.sun_pulse !== false ? 0.6 + 0.2 * Math.sin(t * Math.PI / 90) : 0.5;
    effects.style("sun",     { color: "#facc15", emissive: "#f59e0b", emissiveIntensity: sunEmissive });
    effects.style("mercury", { color: "#cbd5e1" });
    effects.style("venus",   { color: "#fb923c" });
    effects.style("earth",   { color: "#3b82f6", emissive: "#1e40af", emissiveIntensity: 0.2 });
    effects.style("moon",    { color: "#f1f5f9" });
    effects.style("mars",    { color: "#ef4444", emissive: "#7f1d1d", emissiveIntensity: 0.15 });
    effects.style("jupiter", { color: "#f97316", emissive: "#7c2d12", emissiveIntensity: 0.1 });
    effects.style("saturn",  { color: "#fde047" });
    for (const o of ["orbit_mercury","orbit_venus","orbit_earth","orbit_mars","orbit_jupiter","orbit_saturn"]) {
      effects.style(o, { color: "#475569", emissive: "#1e293b", emissiveIntensity: 0.08 });
      effects.visible(o, showOrbits);
    }

    // ---- Orbit + self-spin transforms ----
    const sunPivot = [0, 0, 0];
    function orbitAndSpin(name, speed, orbitRadius) {
      const angle = t * speed;
      const spin = t * SPIN[name];
      effects.transform(name, {
        transforms: [
          // Self-spin around the planet's local Z (at its initial position)
          { rotate: { axis: [0, 0, 1], origin: [orbitRadius, 0, 0], angleDeg: spin } },
          // Orbit around the Sun
          { rotate: { axis: [0, 0, 1], origin: sunPivot, angleDeg: angle } }
        ]
      });
    }

    orbitAndSpin("mercury", SPEED.mercury, 170);
    orbitAndSpin("venus",   SPEED.venus,   240);
    orbitAndSpin("earth",   SPEED.earth,   EARTH_ORBIT);
    orbitAndSpin("mars",    SPEED.mars,    410);
    orbitAndSpin("jupiter", SPEED.jupiter, 560);
    orbitAndSpin("saturn",  SPEED.saturn,  720);

    // Sun self-spin (in place)
    effects.transform("sun", {
      rotate: { axis: [0, 0, 1], origin: sunPivot, angleDeg: t * 0.4 }
    });

    // Moon: orbits Earth (at Earth's initial position), then rides Earth's
    // own solar orbit. The order matters - `transforms[0]` applies to the
    // vertex first.
    const earthAngle = t * SPEED.earth;
    const moonAngle  = t * SPEED.moon;
    effects.transform("moon", {
      transforms: [
        { rotate: { axis: [0, 0, 1], origin: [EARTH_ORBIT, 0, 0], angleDeg: moonAngle } },
        { rotate: { axis: [0, 0, 1], origin: sunPivot,             angleDeg: earthAngle } }
      ]
    });
  }
};
