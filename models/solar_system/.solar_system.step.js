/* Realistic solar system sidecar.
 *
 * `time` (deg, animated 0..360) is Earth's orbital phase. Every other
 * planet's orbit is scaled by the inverse of its real orbital period in
 * Earth years; outer-planet speeds are gently lifted on a log curve so
 * Neptune still moves a little during one Earth year in the viewer.
 *
 * Self-rotation periods are similarly compressed - Earth doesn't really
 * spin 365× per orbit while we watch.
 *
 * Earth's Moon and Jupiter's 4 Galilean moons ride their parent planet's
 * orbital frame via a composed `transforms[]` chain.
 *
 * Geometry constants must match solar_system.py.
 */

const EARTH_ORBIT   = 285;
const JUPITER_ORBIT = 495;

// Orbital radii used to anchor each planet's self-spin / orbit rotation.
const ORBIT = {
  mercury: 150, venus: 210, earth: EARTH_ORBIT, mars: 360,
  jupiter: JUPITER_ORBIT, saturn: 620, uranus: 760, neptune: 895
};

// Orbital speed multipliers (Earth = 1) - inverse of real orbital periods,
// with the outer planets gently boosted so the animation breathes.
const REAL_PERIODS = {
  mercury: 0.241, venus: 0.615, earth: 1.0, mars: 1.881,
  jupiter: 11.86, saturn: 29.46, uranus: 84.01, neptune: 164.79
};
function speedFromPeriod(period) {
  // Pure 1/T for inner, log-compressed for slower-than-Earth planets.
  if (period <= 1.0) return 1.0 / period;
  return 1.0 / Math.pow(period, 0.55);
}
const SPEED = Object.fromEntries(
  Object.entries(REAL_PERIODS).map(([k, p]) => [k, speedFromPeriod(p)])
);

// Self-spin multipliers (visual, not physical)
const SPIN = {
  mercury: 1.2,  venus: -0.4 /* retrograde */, earth: 6.0, mars: 5.8,
  jupiter: 14.0, saturn: 12.5, uranus: -8.0 /* retrograde */, neptune: 7.0
};
const MOON_SPIN = {
  moon: 0.5, io: 2.0, europa: 1.2, ganymede: 0.7, callisto: 0.5
};

// Moon orbital speed multipliers (relative to Earth orbit), inflated for visibility.
const MOON_SPEED = {
  moon: 13.0,         // ~13 lunar months / Earth year
  io: 12.0, europa: 8.0, ganymede: 5.5, callisto: 4.0   // each successively slower
};

const DEG = Math.PI / 180;

export default {
  manifest: {
    schemaVersion: 1,
    parameters: {
      time: {
        type: "number",
        label: "Earth year",
        description: "Earth's orbital phase (0..360°). One full sweep = one Earth year.",
        unit: "deg",
        min: 0,
        max: 360,
        step: 1,
        default: 0
      },
      show_orbits:  { type: "boolean", label: "Show orbit guides",  default: true },
      show_belt:    { type: "boolean", label: "Show asteroid belt", default: true },
      sun_pulse:    { type: "boolean", label: "Solar corona pulse", default: true }
    },
    features: {
      sun:           { ref: "#o1.1" },
      orbit_mercury: { ref: "#o1.2" },
      orbit_venus:   { ref: "#o1.3" },
      orbit_earth:   { ref: "#o1.4" },
      orbit_mars:    { ref: "#o1.5" },
      orbit_jupiter: { ref: "#o1.6" },
      orbit_saturn:  { ref: "#o1.7" },
      orbit_uranus:  { ref: "#o1.8" },
      orbit_neptune: { ref: "#o1.9" },
      asteroid_belt: { ref: "#o1.10" },
      mercury:       { ref: "#o1.11" },
      venus:         { ref: "#o1.12" },
      earth:         { ref: "#o1.13" },
      moon:          { ref: "#o1.14" },
      mars:          { ref: "#o1.15" },
      jupiter:       { ref: "#o1.16" },
      io:            { ref: "#o1.17" },
      europa:        { ref: "#o1.18" },
      ganymede:      { ref: "#o1.19" },
      callisto:      { ref: "#o1.20" },
      saturn:        { ref: "#o1.21" },
      uranus:        { ref: "#o1.22" },
      neptune:       { ref: "#o1.23" }
    },
    animations: {
      orbit: { duration: 16, loop: true }
    }
  },

  update(ctx) {
    const { params, effects } = ctx;
    const t = Number(params.time) || 0;
    const showOrbits = params.show_orbits !== false;
    const showBelt = params.show_belt !== false;
    const sunPulseOn = params.sun_pulse !== false;

    // ---- Realistic-ish palette (no textures; emissive lifts contrast) ----
    // The Sun gets aggressive emissive so the viewer-side bloom pass turns
    // it into a true bright disc.
    const sunPulse = sunPulseOn
      ? 1.8 + 0.4 * Math.sin(t * Math.PI / 90)
      : 1.8;
    effects.style("sun",     { color: "#fde68a", emissive: "#f59e0b", emissiveIntensity: sunPulse });
    effects.style("mercury", { color: "#9ca3af" });                                       // grey-tan
    effects.style("venus",   { color: "#facc15", emissive: "#a16207", emissiveIntensity: 0.18 }); // pale gold haze
    effects.style("earth",   { color: "#3b82f6", emissive: "#1d4ed8", emissiveIntensity: 0.22 });
    effects.style("moon",    { color: "#e5e7eb" });
    effects.style("mars",    { color: "#dc2626", emissive: "#7f1d1d", emissiveIntensity: 0.18 });
    effects.style("jupiter", { color: "#fb923c", emissive: "#7c2d12", emissiveIntensity: 0.16 });
    effects.style("io",       { color: "#fde047" });   // yellow sulfur
    effects.style("europa",   { color: "#fef3c7" });   // pale ice
    effects.style("ganymede", { color: "#a8a29e" });
    effects.style("callisto", { color: "#78716c" });
    effects.style("saturn",  { color: "#fcd34d", emissive: "#92400e", emissiveIntensity: 0.14 });
    effects.style("uranus",  { color: "#67e8f9", emissive: "#155e75", emissiveIntensity: 0.18 });
    effects.style("neptune", { color: "#3b82f6", emissive: "#1e3a8a", emissiveIntensity: 0.22 });
    const orbitNames = ["orbit_mercury","orbit_venus","orbit_earth","orbit_mars",
                        "orbit_jupiter","orbit_saturn","orbit_uranus","orbit_neptune"];
    for (const o of orbitNames) {
      effects.style(o, { color: "#475569", emissive: "#1e293b", emissiveIntensity: 0.1 });
      effects.visible(o, showOrbits);
    }
    effects.style("asteroid_belt", { color: "#a3a3a3" });
    effects.visible("asteroid_belt", showBelt);

    // ---- Sun: spin in place (very slow) ----
    effects.transform("sun", {
      rotate: { axis: [0, 0, 1], origin: [0, 0, 0], angleDeg: t * 0.25 }
    });

    // ---- Planet orbit + self-spin ----
    function planet(name) {
      const orbitR = ORBIT[name];
      const angle = t * SPEED[name];
      const spin = t * SPIN[name];
      effects.transform(name, {
        transforms: [
          { rotate: { axis: [0, 0, 1], origin: [orbitR, 0, 0], angleDeg: spin } },
          { rotate: { axis: [0, 0, 1], origin: [0, 0, 0],      angleDeg: angle } }
        ]
      });
    }
    for (const p of ["mercury", "venus", "earth", "mars", "jupiter",
                     "saturn", "uranus", "neptune"]) {
      planet(p);
    }

    // ---- Earth's Moon: ride Earth's orbit, then orbit Earth ----
    const earthAngle = t * SPEED.earth;
    const moonAngle  = t * MOON_SPEED.moon;
    effects.transform("moon", {
      transforms: [
        { rotate: { axis: [0, 0, 1], origin: [EARTH_ORBIT, 0, 0], angleDeg: moonAngle } },
        { rotate: { axis: [0, 0, 1], origin: [0, 0, 0],           angleDeg: earthAngle } }
      ]
    });

    // ---- Galilean moons: ride Jupiter's orbit, then orbit Jupiter ----
    const jupAngle = t * SPEED.jupiter;
    function galilean(name) {
      const moonAng = t * MOON_SPEED[name];
      effects.transform(name, {
        transforms: [
          { rotate: { axis: [0, 0, 1], origin: [JUPITER_ORBIT, 0, 0], angleDeg: moonAng } },
          { rotate: { axis: [0, 0, 1], origin: [0, 0, 0],             angleDeg: jupAngle } }
        ]
      });
    }
    for (const m of ["io", "europa", "ganymede", "callisto"]) galilean(m);
  }
};
