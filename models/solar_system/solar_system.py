"""Stylised inner solar system: Sun + Mercury, Venus, Earth (+ Moon),
Mars, Jupiter, plus Saturn with a ring.

Units: millimeters. +X / +Y are the orbital plane, +Z is up. Origin at
the Sun's center. Sizes are *not* to scale - planets are inflated and
orbital radii are compressed so everything stays in one frame.

The .step.js sidecar rotates each planet around its orbital pivot at a
speed roughly proportional to the inverse of Kepler's third law, and
spins each body around its own axis. Earth's Moon rides on top of
Earth's orbital rotation, so the kinematic chain is Sun -> Earth orbit
-> Moon orbit.
"""

from __future__ import annotations

import math

from build123d import (
    Align,
    Compound,
    Cylinder,
    Pos,
    Rot,
    Solid,
    Sphere,
    Torus,
)

# --------------------------------------------------------------------------- #
# Sizes (mm) - scaled for visualization, not physically accurate.
# --------------------------------------------------------------------------- #
SUN_R = 90.0

MERCURY = dict(r=10.0, orbit=170.0)
VENUS   = dict(r=15.0, orbit=240.0)
EARTH   = dict(r=18.0, orbit=320.0)
MOON    = dict(r=6.0,  orbit=42.0)   # orbit around Earth
MARS    = dict(r=13.0, orbit=410.0)
JUPITER = dict(r=46.0, orbit=560.0)
SATURN  = dict(r=40.0, orbit=720.0, ring_inner=58.0, ring_outer=92.0, ring_thick=4.0)

ORBIT_PLANE_Z = 0.0
ORBIT_RING_THICK = 1.5       # thin visible orbit lines

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
    """A thin flat torus drawn in the orbital plane (XY)."""
    body = Torus(major_radius=radius, minor_radius=ORBIT_RING_THICK)
    body = Pos(0, 0, ORBIT_PLANE_Z) * body
    return _compound_of((body,), label=label)


# --------------------------------------------------------------------------- #
# Parts
# --------------------------------------------------------------------------- #


def make_sun() -> Compound:
    body = Sphere(SUN_R)
    return _compound_of((body,), label="sun")


def make_planet(spec, label) -> Compound:
    """Sphere placed at (orbit, 0, 0) so the sidecar can rotate it around
    the Sun by simple Z-axis rotation."""
    body = Pos(spec["orbit"], 0, 0) * Sphere(spec["r"])
    return _compound_of((body,), label=label)


def make_earth() -> Compound:
    body = Pos(EARTH["orbit"], 0, 0) * Sphere(EARTH["r"])
    return _compound_of((body,), label="earth")


def make_moon() -> Compound:
    """Moon modeled at Earth's initial position + a Moon orbit offset.

    Sidecar applies (1) Moon orbit rotation around Earth's initial position
    THEN (2) Earth orbit rotation around the Sun. The chain places the Moon
    at the right world position for any (earth_angle, moon_angle) pair.
    """
    body = Pos(EARTH["orbit"] + MOON["orbit"], 0, 0) * Sphere(MOON["r"])
    return _compound_of((body,), label="moon")


def make_saturn() -> Compound:
    body = Pos(SATURN["orbit"], 0, 0) * Sphere(SATURN["r"])
    # Ring as an annular disc lying in the orbital plane around the planet
    outer = Cylinder(SATURN["ring_outer"], SATURN["ring_thick"],
                     align=(Align.CENTER, Align.CENTER, Align.CENTER))
    inner = Cylinder(SATURN["ring_inner"], SATURN["ring_thick"] + 1,
                     align=(Align.CENTER, Align.CENTER, Align.CENTER))
    ring = outer - inner
    # Tilt the ring slightly off-plane so it reads as a disc, not a circle
    ring = Rot(0, 18, 0) * ring
    ring = Pos(SATURN["orbit"], 0, 0) * ring
    return _compound_of((body, ring), label="saturn")


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def gen_step() -> Compound:
    children = [
        make_sun(),                                  # o1.1
        _orbit_ring(MERCURY["orbit"], "orbit_mercury"),   # o1.2
        _orbit_ring(VENUS["orbit"],   "orbit_venus"),     # o1.3
        _orbit_ring(EARTH["orbit"],   "orbit_earth"),     # o1.4
        _orbit_ring(MARS["orbit"],    "orbit_mars"),      # o1.5
        _orbit_ring(JUPITER["orbit"], "orbit_jupiter"),   # o1.6
        _orbit_ring(SATURN["orbit"],  "orbit_saturn"),    # o1.7
        make_planet(MERCURY, "mercury"),             # o1.8
        make_planet(VENUS,   "venus"),               # o1.9
        make_earth(),                                # o1.10
        make_moon(),                                 # o1.11
        make_planet(MARS,    "mars"),                # o1.12
        make_planet(JUPITER, "jupiter"),             # o1.13
        make_saturn(),                               # o1.14
    ]
    return Compound(label="solar_system", children=children)


if __name__ == "__main__":
    sol = gen_step()
    print(f"children: {len(sol.children)}")
    for i, c in enumerate(sol.children, start=1):
        print(f"  o1.{i}: {c.label}")
