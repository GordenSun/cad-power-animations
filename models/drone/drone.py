"""Quadcopter drone — body, 4 arms, 4 motors, 4 propellers.

Units: millimeters.
Convention: +X forward (nose), +Y left, +Z up. Drone hovers at z=BODY_Z.

X-pattern arms (45 degrees from +X). Propeller pairs spin opposite for
torque balance (FR + RL clockwise, FL + RR counter-clockwise when viewed
from above).
"""

from __future__ import annotations

import math

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
    Sphere,
    Vector,
)

# --------------------------------------------------------------------------- #
# Parameters
# --------------------------------------------------------------------------- #
BODY_Z = 220.0                 # cruise altitude in mm
BODY_LEN = 240.0               # along X (nose-tail)
BODY_WIDTH = 170.0             # along Y
BODY_HEIGHT = 70.0             # along Z

MOTOR_DISTANCE = 360.0         # distance from body center to each motor
ARM_R = 16.0                   # arm tube radius

MOTOR_R = 36.0
MOTOR_LEN = 60.0
PROP_LENGTH = 280.0            # tip-to-tip
PROP_WIDTH = 28.0
PROP_THICK = 6.0
PROP_Z_OFFSET = MOTOR_LEN / 2 + 8  # prop sits above the motor cap

LEG_LEN = 160.0
LEG_R = 8.0
SKID_LEN = 220.0
SKID_R = 9.0

# Motor positions (X-pattern, 45 deg from +X)
_D = MOTOR_DISTANCE / math.sqrt(2)
MOTOR_POSITIONS = {
    "fl": (+_D, +_D, BODY_Z),  # front-left
    "fr": (+_D, -_D, BODY_Z),  # front-right
    "rl": (-_D, +_D, BODY_Z),  # rear-left
    "rr": (-_D, -_D, BODY_Z),  # rear-right
}

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
        for it in piece:
            out.extend(_to_solids(it))
        return out
    return [piece]


def _compound_of(pieces, label=None):
    solids = []
    for p in pieces:
        solids.extend(_to_solids(p))
    body = Compound(label=label or "", children=solids)
    if label:
        body.label = label
    return body


def _vec(p):
    return p if isinstance(p, Vector) else Vector(*p)


def _tube_between(p1, p2, radius):
    p1v = _vec(p1)
    p2v = _vec(p2)
    diff = p2v - p1v
    length = diff.length
    if length < 1e-6:
        return Cylinder(radius, 0.1, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    direction = diff * (1.0 / length)
    midpoint = (p1v + p2v) * 0.5
    plane = Plane(origin=midpoint, z_dir=direction)
    return plane * Cylinder(radius, length,
                            align=(Align.CENTER, Align.CENTER, Align.CENTER))


def _cyl_along(axis, radius, length, center=(0, 0, 0)):
    base = Cylinder(radius, length, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    if axis.upper() == "X":
        base = Rot(0, 90, 0) * base
    elif axis.upper() == "Y":
        base = Rot(90, 0, 0) * base
    return Pos(*center) * base


# --------------------------------------------------------------------------- #
# Parts
# --------------------------------------------------------------------------- #


def make_body() -> Compound:
    # Smooth-ish hull: a box with a top dome
    main = Pos(0, 0, BODY_Z) * Box(BODY_LEN, BODY_WIDTH, BODY_HEIGHT,
                                   align=(Align.CENTER, Align.CENTER, Align.CENTER))
    canopy = Pos(0, 0, BODY_Z + BODY_HEIGHT / 2) * Sphere(BODY_WIDTH / 2)
    # Flatten canopy by intersecting with a top slab
    nose = Pos(BODY_LEN / 2 - 10, 0, BODY_Z + BODY_HEIGHT / 4) * Sphere(40)
    return _compound_of([main, canopy, nose], label="body")


def make_arm(label_suffix: str, motor_xyz) -> Compound:
    """Tube from body edge to motor position, on the upper deck."""
    body_attach = (0, 0, BODY_Z + 5)
    arm = _tube_between(body_attach, motor_xyz, ARM_R)
    return _compound_of([arm], label=f"arm_{label_suffix}")


def make_motor(label_suffix: str, motor_xyz) -> Compound:
    motor = _cyl_along("Z", MOTOR_R, MOTOR_LEN, center=motor_xyz)
    cap = _cyl_along("Z", MOTOR_R + 4, 8,
                     center=(motor_xyz[0], motor_xyz[1], motor_xyz[2] + MOTOR_LEN / 2 - 2))
    return _compound_of([motor, cap], label=f"motor_{label_suffix}")


def make_prop(label_suffix: str, motor_xyz) -> Compound:
    """Two-blade prop modeled as a thin flat slab with a hub."""
    z = motor_xyz[2] + PROP_Z_OFFSET
    blade = Pos(motor_xyz[0], motor_xyz[1], z) * Box(
        PROP_LENGTH, PROP_WIDTH, PROP_THICK,
        align=(Align.CENTER, Align.CENTER, Align.CENTER)
    )
    hub = _cyl_along("Z", 22, PROP_THICK + 6,
                     center=(motor_xyz[0], motor_xyz[1], z))
    return _compound_of([blade, hub], label=f"prop_{label_suffix}")


def make_landing_gear() -> Compound:
    """Two longitudinal skids with vertical legs, under the body."""
    pieces = []
    z_skid = BODY_Z - BODY_HEIGHT / 2 - LEG_LEN
    for y in (+90, -90):
        for x in (+SKID_LEN / 3, -SKID_LEN / 3):
            leg = _cyl_along("Z", LEG_R, LEG_LEN,
                             center=(x, y, BODY_Z - BODY_HEIGHT / 2 - LEG_LEN / 2))
            pieces.append(leg)
        skid = _cyl_along("X", SKID_R, SKID_LEN,
                          center=(0, y, z_skid + SKID_R))
        pieces.append(skid)
    return _compound_of(pieces, label="landing_gear")


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def gen_step() -> Compound:
    children = [
        make_body(),                                  # o1.1
        make_landing_gear(),                          # o1.2
        make_arm("fl", MOTOR_POSITIONS["fl"]),        # o1.3
        make_arm("fr", MOTOR_POSITIONS["fr"]),        # o1.4
        make_arm("rl", MOTOR_POSITIONS["rl"]),        # o1.5
        make_arm("rr", MOTOR_POSITIONS["rr"]),        # o1.6
        make_motor("fl", MOTOR_POSITIONS["fl"]),      # o1.7
        make_motor("fr", MOTOR_POSITIONS["fr"]),      # o1.8
        make_motor("rl", MOTOR_POSITIONS["rl"]),      # o1.9
        make_motor("rr", MOTOR_POSITIONS["rr"]),      # o1.10
        make_prop("fl", MOTOR_POSITIONS["fl"]),       # o1.11
        make_prop("fr", MOTOR_POSITIONS["fr"]),       # o1.12
        make_prop("rl", MOTOR_POSITIONS["rl"]),       # o1.13
        make_prop("rr", MOTOR_POSITIONS["rr"]),       # o1.14
    ]
    return Compound(label="quadcopter", children=children)


if __name__ == "__main__":
    g = gen_step()
    print(f"children: {len(g.children)}")
    for i, c in enumerate(g.children, 1):
        print(f"  o1.{i}: {c.label}")
