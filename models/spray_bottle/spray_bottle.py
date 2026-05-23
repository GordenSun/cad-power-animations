"""Trigger spray bottle — small piston pump.

Units: millimeters. +X forward (the nozzle points +X), +Y left, +Z up.
Origin on the ground beneath the bottle's centerline.

The bottle is the static body. The trigger is a lever pinned at the
pivot pin; it pulls a piston that slides inside a horizontal pump
chamber. As the trigger swings, the piston compresses the chamber and
pushes liquid out the nozzle — visible as a cone of spray that the
sidecar pops in and out at the right moment in the cycle.
"""

from __future__ import annotations

import math

from build123d import (
    Align,
    Box,
    Compound,
    Cone,
    Cylinder,
    Location,
    Plane,
    Pos,
    Rot,
    Solid,
    Sphere,
    Vector,
)

# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #
BOTTLE_R = 50.0
BOTTLE_H = 160.0
BOTTLE_Z = BOTTLE_H / 2          # bottle center Z
BOTTLE_NECK_R = 18.0
BOTTLE_NECK_H = 14.0

LIQUID_R = BOTTLE_R - 2.5
LIQUID_H = BOTTLE_H * 0.7        # initial fill level visually

CAP_R = BOTTLE_R + 3.0
CAP_H = 16.0
CAP_Z = BOTTLE_H + BOTTLE_NECK_H + CAP_H / 2

# Head assembly sits on top of the cap
HEAD_Z = CAP_Z + CAP_H / 2

# Pump chamber: horizontal cylinder pointing +X out of the head
PUMP_R = 9.0
PUMP_LENGTH = 56.0
PUMP_X_CENTER = 30.0
PUMP_Z = HEAD_Z + 18.0

PISTON_R = 7.5
PISTON_THICK = 10.0
# Piston modeled at the rear of the chamber (cocked, ready to fire)
PISTON_X_REST = PUMP_X_CENTER - PUMP_LENGTH / 2 + PISTON_THICK / 2 + 4
PISTON_STROKE = 28.0             # max travel toward the nozzle

# Trigger lever: pinned at PIVOT, swings to pull/push the piston
PIVOT_X = PUMP_X_CENTER + PUMP_LENGTH / 2 - 4
PIVOT_Z = PUMP_Z + 6.0
TRIGGER_LENGTH = 80.0
TRIGGER_THICK = 8.0
TRIGGER_WIDTH = 18.0
TRIGGER_REST_DEG = 10.0          # tilted slightly forward at rest

# Nozzle: short stub forward of the head
NOZZLE_R = 4.5
NOZZLE_LENGTH = 18.0
NOZZLE_X_END = PUMP_X_CENTER + PUMP_LENGTH / 2 + NOZZLE_LENGTH

# Spray cone: a thin Cone going from the nozzle into +X; sidecar hides it
# when the bottle isn't actively spraying.
SPRAY_BASE_R = 26.0
SPRAY_LENGTH = 240.0

# Dip tube going from the cap down to the bottle bottom
DIP_R = 2.6
DIP_TOP_Z = CAP_Z + CAP_H / 2
DIP_BOTTOM_Z = 6.0

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


def _cyl_along(axis, radius, length, center=(0, 0, 0)):
    base = Cylinder(radius, length, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    if axis.upper() == "X":
        base = Rot(0, 90, 0) * base
    elif axis.upper() == "Y":
        base = Rot(90, 0, 0) * base
    return Pos(*center) * base


def _cone_along_x(base_r, tip_r, length, center) -> Solid:
    """Cone with axis along +X, tip toward +X."""
    body = Cone(base_r, tip_r, length, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    # default Cone is along Z; rotate it +90° around -Y to align axis with +X
    body = Rot(0, 90, 0) * body
    body = Pos(*center) * body
    return body


# --------------------------------------------------------------------------- #
# Parts
# --------------------------------------------------------------------------- #


def make_bottle() -> Compound:
    """Bottle body + neck. Static."""
    body = _cyl_along("Z", BOTTLE_R, BOTTLE_H, center=(0, 0, BOTTLE_Z))
    neck = _cyl_along("Z", BOTTLE_NECK_R, BOTTLE_NECK_H,
                      center=(0, 0, BOTTLE_H + BOTTLE_NECK_H / 2))
    return _compound_of((body, neck), label="bottle")


def make_liquid() -> Compound:
    """Liquid inside the bottle, modeled at default fill level. The sidecar
    rescales its Z to follow the `fill_level` parameter."""
    body = _cyl_along("Z", LIQUID_R, LIQUID_H, center=(0, 0, LIQUID_H / 2))
    return _compound_of((body,), label="liquid")


def make_cap() -> Compound:
    body = _cyl_along("Z", CAP_R, CAP_H, center=(0, 0, CAP_Z))
    return _compound_of((body,), label="cap")


def make_head() -> Compound:
    """Plastic head block carrying the pump chamber and nozzle."""
    block = Pos(20, 0, HEAD_Z + 22) * Box(80, 38, 44,
        align=(Align.CENTER, Align.CENTER, Align.CENTER))
    chamber = _cyl_along("X", PUMP_R + 1.5, PUMP_LENGTH + 4,
                         center=(PUMP_X_CENTER, 0, PUMP_Z))
    nozzle = _cyl_along("X", NOZZLE_R, NOZZLE_LENGTH,
                        center=(NOZZLE_X_END - NOZZLE_LENGTH / 2, 0, PUMP_Z))
    return _compound_of((block, chamber, nozzle), label="head")


def make_piston() -> Compound:
    body = _cyl_along("X", PISTON_R, PISTON_THICK,
                      center=(PISTON_X_REST, 0, PUMP_Z))
    # Piston rod sticking out the back so the trigger can grab it
    rod = _cyl_along("X", PISTON_R * 0.45, 30,
                     center=(PISTON_X_REST + 22, 0, PUMP_Z))
    return _compound_of((body, rod), label="piston")


def make_trigger() -> Compound:
    """Lever modeled at its rest position. Sidecar rotates it around PIVOT
    along the Y axis to pull the piston."""
    # Lever body extending down and slightly forward from the pivot
    angle = math.radians(TRIGGER_REST_DEG)
    end_x = PIVOT_X + math.sin(angle) * TRIGGER_LENGTH
    end_z = PIVOT_Z - math.cos(angle) * TRIGGER_LENGTH
    midpoint = ((PIVOT_X + end_x) / 2, 0, (PIVOT_Z + end_z) / 2)
    # Use a tilted box to represent the lever
    body = Box(TRIGGER_THICK, TRIGGER_WIDTH, TRIGGER_LENGTH,
               align=(Align.CENTER, Align.CENTER, Align.CENTER))
    # Tilt around Y by TRIGGER_REST_DEG so the lever leans forward at rest
    body = Rot(0, -TRIGGER_REST_DEG, 0) * body
    body = Pos(*midpoint) * body
    # Pivot collar
    collar = _cyl_along("Y", 9.0, TRIGGER_WIDTH + 6,
                        center=(PIVOT_X, 0, PIVOT_Z))
    # Finger pad at the bottom of the lever
    pad = Pos(end_x - 6, 0, end_z + 6) * Box(22, TRIGGER_WIDTH + 4, 18,
        align=(Align.CENTER, Align.CENTER, Align.CENTER))
    return _compound_of((body, collar, pad), label="trigger")


def make_dip_tube() -> Compound:
    body = _cyl_along("Z", DIP_R, DIP_TOP_Z - DIP_BOTTOM_Z,
                      center=(0, 0, (DIP_TOP_Z + DIP_BOTTOM_Z) / 2))
    return _compound_of((body,), label="dip_tube")


def make_spray_cone() -> Compound:
    """A short fan-shaped cone in front of the nozzle. Hidden by default."""
    start_x = NOZZLE_X_END + 2
    body = _cone_along_x(2.0, SPRAY_BASE_R, SPRAY_LENGTH,
                         center=(start_x + SPRAY_LENGTH / 2, 0, PUMP_Z))
    # A few small droplet spheres to suggest droplets at the far edge
    droplets = []
    for i in range(6):
        ang = (i / 6) * math.pi * 2
        r = SPRAY_BASE_R * 0.9
        droplets.append(
            Pos(start_x + SPRAY_LENGTH - 6,
                r * 0.5 * math.cos(ang),
                PUMP_Z + r * 0.5 * math.sin(ang)) * Sphere(2.2)
        )
    return _compound_of((body, *droplets), label="spray")


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def gen_step() -> Compound:
    children = [
        make_bottle(),       # o1.1
        make_liquid(),       # o1.2
        make_cap(),          # o1.3
        make_head(),         # o1.4
        make_dip_tube(),     # o1.5
        make_piston(),       # o1.6
        make_trigger(),      # o1.7
        make_spray_cone(),   # o1.8
    ]
    return Compound(label="spray_bottle", children=children)


if __name__ == "__main__":
    obj = gen_step()
    print(f"children: {len(obj.children)}")
    for i, c in enumerate(obj.children, start=1):
        print(f"  o1.{i}: {c.label}")
