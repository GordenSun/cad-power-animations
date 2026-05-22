"""Planetary gearbox — sun + three planets + ring + carrier.

Units: millimeters.
Convention: rotation axis along +Y. All gears live in the XZ plane,
extruded along Y. Origin at the sun centerline on the gear midplane.

The sidecar drives the sun gear with `drive` (input angle in degrees);
all other elements follow from the standard planetary-gear kinematics
(ring fixed, carrier output):

    ω_carrier = ω_sun * Zs / (Zs + Zr)
    ω_planet_world = -ω_sun * Zs / Zp + ω_carrier (1 + Zs / Zp)

With Zs=12, Zp=18, Zr=48 (matching the geometry below), the carrier
turns at 0.2 × the sun and each planet spins at -1/3 × the sun in world
frame, so the colored teeth are clearly readable.
"""

from __future__ import annotations

import math
from typing import Iterable

from build123d import (
    Align,
    Box,
    Compound,
    Cylinder,
    Location,
    Plane,
    Pos,
    Rot,
    Solid,
    Vector,
)

# --------------------------------------------------------------------------- #
# Gear parameters (tooth counts drive the kinematics; geometry follows)
# --------------------------------------------------------------------------- #
SUN_TEETH = 12
PLANET_TEETH = 18
RING_TEETH = SUN_TEETH + 2 * PLANET_TEETH  # 48

MODULE = 8.0                       # mm per tooth (visual size)
SUN_R = SUN_TEETH * MODULE / 2     # 48
PLANET_R = PLANET_TEETH * MODULE / 2  # 72
RING_R_INNER = RING_TEETH * MODULE / 2  # 192 (pitch radius)
RING_R_OUTER = RING_R_INNER + 28.0      # 220

CARRIER_RADIUS = SUN_R + PLANET_R       # 120 (planet center distance from sun)

TOOTH_TANG = MODULE * 0.55          # tangential width
TOOTH_RADIAL = MODULE * 0.85        # radial protrusion
GEAR_THICK = 40.0                    # axial thickness

CARRIER_DISC_R = CARRIER_RADIUS + 25.0
CARRIER_THICK = 12.0
# Carrier sits BEHIND the gears (positive Y) so it never occludes the
# coloured planets when the viewer camera is on the -Y side.
CARRIER_Y_OFFSET = +(GEAR_THICK / 2 + CARRIER_THICK / 2 + 4)

INPUT_SHAFT_R = 16.0
INPUT_SHAFT_LEN = 140.0
OUTPUT_SHAFT_R = 22.0
OUTPUT_SHAFT_LEN = 140.0

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _to_solids(piece) -> list[Solid]:
    if isinstance(piece, Solid):
        return [piece]
    if isinstance(piece, Compound):
        return list(piece.solids())
    if hasattr(piece, "__iter__"):
        out: list[Solid] = []
        for item in piece:
            out.extend(_to_solids(item))
        return out
    return [piece]


def _compound_of(pieces, label: str | None = None) -> Compound:
    solids: list[Solid] = []
    for piece in pieces:
        solids.extend(_to_solids(piece))
    body = Compound(label=label or "", children=solids)
    if label:
        body.label = label
    return body


def _cyl_along(axis: str, radius: float, length: float, center=(0, 0, 0)) -> Solid:
    base = Cylinder(radius, length, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    if axis.upper() == "X":
        base = Rot(0, 90, 0) * base
    elif axis.upper() == "Y":
        base = Rot(90, 0, 0) * base
    return Pos(*center) * base


def _tooth_box(theta_rad: float, pitch_r: float, w_tang: float, axial: float,
               h_radial: float, center=(0, 0, 0), inward: bool = False) -> Solid:
    """Rectangular tooth at angle theta_rad on a circle of radius pitch_r.
    Tooth h_radial dimension extends outward (or inward) from the pitch line."""
    sign = -1 if inward else +1
    cx = center[0] + (pitch_r + sign * h_radial / 2) * math.cos(theta_rad)
    cz = center[2] + (pitch_r + sign * h_radial / 2) * math.sin(theta_rad)
    cy = center[1]
    # Rotation around Y to align the box's Z axis with the radial direction
    rot_deg = 90.0 - math.degrees(theta_rad)
    box = Box(w_tang, axial, h_radial, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    return Pos(cx, cy, cz) * (Rot(0, rot_deg, 0) * box)


def make_spur_gear(label: str, radius: float, n_teeth: int, thickness: float,
                   center=(0, 0, 0), bore_r: float = 0.0) -> Compound:
    """A spur gear with N external teeth on the perimeter."""
    body = _cyl_along("Y", radius, thickness, center=center)
    if bore_r > 0:
        bore = _cyl_along("Y", bore_r, thickness + 2, center=center)
        body = body - bore
    teeth = []
    for i in range(n_teeth):
        theta = i * 2 * math.pi / n_teeth
        teeth.append(_tooth_box(theta, radius, TOOTH_TANG, thickness,
                                TOOTH_RADIAL, center=center))
    return _compound_of([body] + teeth, label=label)


def make_ring_gear(label: str, inner_pitch_r: float, outer_r: float,
                   n_teeth: int, thickness: float, center=(0, 0, 0)) -> Compound:
    """A ring gear: hollow tube with teeth pointing inward."""
    outer = _cyl_along("Y", outer_r, thickness, center=center)
    inner_cut = _cyl_along("Y", inner_pitch_r + TOOTH_RADIAL / 2,
                           thickness + 2, center=center)
    body = outer - inner_cut
    teeth = []
    for i in range(n_teeth):
        theta = i * 2 * math.pi / n_teeth
        teeth.append(_tooth_box(theta, inner_pitch_r, TOOTH_TANG,
                                thickness, TOOTH_RADIAL,
                                center=center, inward=True))
    return _compound_of([body] + teeth, label=label)


# --------------------------------------------------------------------------- #
# Assembly parts
# --------------------------------------------------------------------------- #


def make_ring() -> Compound:
    return make_ring_gear("ring",
                          inner_pitch_r=RING_R_INNER,
                          outer_r=RING_R_OUTER,
                          n_teeth=RING_TEETH,
                          thickness=GEAR_THICK)


def make_sun() -> Compound:
    return make_spur_gear("sun",
                          radius=SUN_R,
                          n_teeth=SUN_TEETH,
                          thickness=GEAR_THICK,
                          bore_r=INPUT_SHAFT_R + 2)


def make_planet(idx: int) -> Compound:
    """Planet i sits at angle (i * 120°) around the sun."""
    theta = idx * (2 * math.pi / 3)
    cx = CARRIER_RADIUS * math.cos(theta)
    cz = CARRIER_RADIUS * math.sin(theta)
    # Build the gear at world origin, then offset to planet position.
    # We build at the offset so the bore axis matches the planet axis.
    return make_spur_gear(f"planet_{idx + 1}",
                          radius=PLANET_R,
                          n_teeth=PLANET_TEETH,
                          thickness=GEAR_THICK,
                          center=(cx, 0, cz),
                          bore_r=18.0)


def make_carrier() -> Compound:
    """Triangular carrier plate behind the gears that connects the three
    planet axes and the sun centerline."""
    disc = _cyl_along("Y", CARRIER_DISC_R, CARRIER_THICK,
                      center=(0, CARRIER_Y_OFFSET, 0))
    # Hub bore for the sun shaft
    bore = _cyl_along("Y", INPUT_SHAFT_R + 2, CARRIER_THICK + 4,
                      center=(0, CARRIER_Y_OFFSET, 0))
    body = disc - bore
    # Small pin discs at each planet position (these stay aligned with the
    # planet centers since the carrier itself rotates).
    pins = []
    for i in range(3):
        theta = i * (2 * math.pi / 3)
        cx = CARRIER_RADIUS * math.cos(theta)
        cz = CARRIER_RADIUS * math.sin(theta)
        pin = _cyl_along("Y", 18, CARRIER_THICK + 6,
                         center=(cx, CARRIER_Y_OFFSET, cz))
        pins.append(pin)
    return _compound_of([body] + pins, label="carrier")


def make_input_shaft() -> Compound:
    """Input shaft sticks out the FRONT (-Y) toward the viewer; rigidly
    attached to the sun."""
    body = _cyl_along("Y", INPUT_SHAFT_R, INPUT_SHAFT_LEN,
                      center=(0, -(GEAR_THICK / 2 + INPUT_SHAFT_LEN / 2 - 5), 0))
    return _compound_of([body], label="input_shaft")


def make_output_shaft() -> Compound:
    """Output shaft sticks out the BACK (+Y); rigidly attached to the
    carrier and rotates at the carrier's slow output speed."""
    body = _cyl_along("Y", OUTPUT_SHAFT_R, OUTPUT_SHAFT_LEN,
                      center=(0,
                              CARRIER_Y_OFFSET + CARRIER_THICK / 2 + OUTPUT_SHAFT_LEN / 2 - 5,
                              0))
    flange = _cyl_along("Y", OUTPUT_SHAFT_R + 18, 12,
                        center=(0,
                                CARRIER_Y_OFFSET + CARRIER_THICK / 2 + 6,
                                0))
    return _compound_of([body, flange], label="output_shaft")


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def gen_step() -> Compound:
    children = [
        make_ring(),           # o1.1
        make_sun(),            # o1.2
        make_planet(0),        # o1.3
        make_planet(1),        # o1.4
        make_planet(2),        # o1.5
        make_carrier(),        # o1.6
        make_input_shaft(),    # o1.7
        make_output_shaft(),   # o1.8
    ]
    return Compound(label="planetary_gearbox", children=children)


if __name__ == "__main__":
    g = gen_step()
    print(f"children: {len(g.children)}")
    for i, c in enumerate(g.children, 1):
        print(f"  o1.{i}: {c.label}")
