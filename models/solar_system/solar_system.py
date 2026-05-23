"""Realistic solar system: Sun + 8 planets, Earth's Moon, Jupiter's four
Galilean moons, a tilted Saturn ring system, and a thin asteroid belt
between Mars and Jupiter.

Units: millimeters. +X / +Y are the orbital plane, +Z is up. Origin at
the Sun's center. Sizes and orbits are compressed (logarithmically for
outer planets) so everything fits one frame, but the RATIOS between
inner planets are roughly correct (e.g. Jupiter ≈ 2.7× Earth radius).

The .step.js sidecar:
  - turns every body at Keplerian-derived orbital periods,
  - spins each planet on its own axis,
  - rides the Moon on Earth's orbital frame,
  - rides the four Galilean moons on Jupiter's orbital frame.
"""

from __future__ import annotations

import math
import random

from build123d import (
    Align,
    Compound,
    Cylinder,
    Pos,
    Rot,
    Solid,
    Sphere,
)

# --------------------------------------------------------------------------- #
# Body sizes (mm). Stylized for visualization but with realistic relative
# proportions between rocky vs gas-giant planets.
# --------------------------------------------------------------------------- #
SUN_R = 95.0

PLANETS = {
    #            radius   orbit   note
    "mercury":  (7.0,    150.0),
    "venus":    (13.0,   210.0),
    "earth":    (14.0,   285.0),
    "mars":     (10.0,   360.0),
    "jupiter":  (38.0,   495.0),
    "saturn":   (32.0,   620.0),
    "uranus":   (22.0,   760.0),
    "neptune":  (21.0,   895.0),
}

EARTH_MOON_R = 4.0
EARTH_MOON_ORBIT = 32.0

JUPITER_MOONS = [
    # name, radius, orbit-from-jupiter
    ("io",        4.0, 56.0),
    ("europa",    3.5, 70.0),
    ("ganymede",  5.5, 88.0),
    ("callisto",  5.0, 110.0),
]

# Saturn ring system (3 concentric bands → reads as the A / B / C rings)
SATURN_RING_TILT_DEG = 26.7   # Saturn's real axial tilt
SATURN_RING_BANDS = [
    # inner, outer, thickness
    (40.0, 50.0, 1.2),   # C ring (innermost, sparse)
    (52.0, 64.0, 1.4),   # B ring (brightest)
    (66.0, 78.0, 1.0),   # A ring
]

# Asteroid belt
BELT_INNER = 395.0
BELT_OUTER = 445.0
BELT_COUNT = 28
BELT_RNG_SEED = 7

# Visual orbit rings (thin tori)
ORBIT_RING_THICK = 1.0

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _to_solids(piece):
    if isinstance(piece, Solid):
        return [piece]
    if isinstance(piece, Compound):
        return list(piece.solids())
    if hasattr(piece, "__iter__"):
        out = []
        for item in piece:
            out.extend(_to_solids(item))
        return out
    return [piece]


def _compound_of(pieces, label):
    solids = []
    for p in pieces:
        solids.extend(_to_solids(p))
    body = Compound(label=label, children=solids)
    body.label = label
    return body


def _orbit_ring(radius, label):
    """A thin flat ring drawn in the orbital plane (XY)."""
    from build123d import Torus
    body = Torus(major_radius=radius, minor_radius=ORBIT_RING_THICK)
    return _compound_of((body,), label=label)


def _annular_disc(inner, outer, thick):
    outer_disc = Cylinder(outer, thick, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    inner_disc = Cylinder(inner, thick + 1, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    return outer_disc - inner_disc


# --------------------------------------------------------------------------- #
# Bodies
# --------------------------------------------------------------------------- #


def make_sun() -> Compound:
    body = Sphere(SUN_R)
    return _compound_of((body,), label="sun")


def make_planet(name) -> Compound:
    r, orbit = PLANETS[name]
    body = Pos(orbit, 0, 0) * Sphere(r)
    return _compound_of((body,), label=name)


def make_earth_moon() -> Compound:
    """Moon modeled at Earth's initial position + a Moon offset; sidecar
    composes its rotation chain (moon-around-earth, then earth-around-sun)."""
    _, earth_orbit = PLANETS["earth"]
    body = Pos(earth_orbit + EARTH_MOON_ORBIT, 0, 0) * Sphere(EARTH_MOON_R)
    return _compound_of((body,), label="moon")


def make_jupiter_moon(name, radius, moon_orbit) -> Compound:
    _, jup_orbit = PLANETS["jupiter"]
    body = Pos(jup_orbit + moon_orbit, 0, 0) * Sphere(radius)
    return _compound_of((body,), label=name)


def make_saturn_with_rings() -> Compound:
    """Saturn body + 3 tilted ring bands as a single labeled compound so the
    sidecar can swing the whole planet through its orbit in one transform."""
    _, sat_orbit = PLANETS["saturn"]
    sat_r, _ = PLANETS["saturn"][0], None  # only need radius below
    body = Pos(sat_orbit, 0, 0) * Sphere(PLANETS["saturn"][0])

    # Build rings in local frame, tilt them by Saturn's axial inclination,
    # then translate to Saturn's initial orbital position.
    ring_pieces = []
    for inner, outer, thick in SATURN_RING_BANDS:
        ring = _annular_disc(inner, outer, thick)
        ring = Rot(SATURN_RING_TILT_DEG, 0, 0) * ring
        ring = Pos(sat_orbit, 0, 0) * ring
        ring_pieces.append(ring)

    return _compound_of((body, *ring_pieces), label="saturn")


def make_asteroid_belt() -> Compound:
    """A few dozen small spheres scattered between Mars and Jupiter on
    randomized orbital radii. The whole belt is one part - it doesn't
    revolve in the sidecar so the random scatter pattern stays put."""
    rnd = random.Random(BELT_RNG_SEED)
    pieces = []
    for _ in range(BELT_COUNT):
        r = rnd.uniform(BELT_INNER, BELT_OUTER)
        theta = rnd.uniform(0, math.tau)
        z = rnd.uniform(-6.0, 6.0)
        size = rnd.uniform(1.6, 3.4)
        pieces.append(Pos(r * math.cos(theta), r * math.sin(theta), z) * Sphere(size))
    return _compound_of(pieces, label="asteroid_belt")


def make_orbit_ring(name) -> Compound:
    """Faint orbit guide ring."""
    _, orbit = PLANETS[name]
    return _orbit_ring(orbit, f"orbit_{name}")


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def gen_step() -> Compound:
    children = []

    # ---- Background guides (drawn first so planets render on top) ----
    children.append(make_sun())                                  # o1.1
    for name in ("mercury", "venus", "earth", "mars",
                 "jupiter", "saturn", "uranus", "neptune"):
        children.append(make_orbit_ring(name))                   # o1.2 .. o1.9
    children.append(make_asteroid_belt())                        # o1.10

    # ---- Planets ----
    children.append(make_planet("mercury"))                      # o1.11
    children.append(make_planet("venus"))                        # o1.12
    children.append(make_planet("earth"))                        # o1.13
    children.append(make_earth_moon())                           # o1.14
    children.append(make_planet("mars"))                         # o1.15
    children.append(make_planet("jupiter"))                      # o1.16
    for moon_name, moon_r, moon_orbit in JUPITER_MOONS:
        children.append(make_jupiter_moon(moon_name, moon_r, moon_orbit))
        # o1.17 io, o1.18 europa, o1.19 ganymede, o1.20 callisto
    children.append(make_saturn_with_rings())                    # o1.21
    children.append(make_planet("uranus"))                       # o1.22
    children.append(make_planet("neptune"))                      # o1.23

    return Compound(label="solar_system", children=children)


if __name__ == "__main__":
    sol = gen_step()
    print(f"children: {len(sol.children)}")
    for i, c in enumerate(sol.children, start=1):
        print(f"  o1.{i}: {c.label}")
