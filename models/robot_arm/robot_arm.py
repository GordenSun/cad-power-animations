"""Five-axis articulated robot arm with a parallel-jaw gripper.

Units: millimeters. +X forward, +Y left, +Z up. Origin at the center of
the base on the ground plane.

Modeled in its zero pose (column up, arm extended along +X). The
.robot_arm.step.js sidecar composes the rotations of joints J0..J4 and
the linear gripper opening to drive the chain forward kinematics.
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
# Geometry constants - kept in sync with the .step.js sidecar.
# --------------------------------------------------------------------------- #
BASE_R = 130.0
BASE_H = 80.0

# J0: yaw axis (vertical) at base center
COLUMN_R = 55.0
COLUMN_TOP_Z = 290.0     # top of column = pivot of J1

# J1: shoulder pitch at (0, 0, COLUMN_TOP_Z), axis +Y
UPPER_ARM_LENGTH = 260.0
UPPER_ARM_W = 80.0
UPPER_ARM_H = 60.0

# J2: elbow pitch at (UPPER_ARM_LENGTH, 0, COLUMN_TOP_Z), axis +Y
FOREARM_LENGTH = 220.0
FOREARM_W = 65.0
FOREARM_H = 55.0

# J3: wrist pitch at (UPPER_ARM_LENGTH+FOREARM_LENGTH, 0, COLUMN_TOP_Z), axis +Y
WRIST_LENGTH = 110.0
WRIST_W = 55.0
WRIST_H = 50.0

# J4: tool roll at (UPPER+FORE+WRIST, 0, COLUMN_TOP_Z), axis +X
GRIPPER_PLATE_T = 18.0
GRIPPER_FINGER_L = 90.0
GRIPPER_FINGER_W = 18.0
GRIPPER_FINGER_H = 30.0
GRIPPER_BASE_OFFSET = 25.0  # plate is just past J4

J0 = (0.0, 0.0, 0.0)
J1 = (0.0, 0.0, COLUMN_TOP_Z)
J2 = (UPPER_ARM_LENGTH, 0.0, COLUMN_TOP_Z)
J3 = (UPPER_ARM_LENGTH + FOREARM_LENGTH, 0.0, COLUMN_TOP_Z)
J4 = (UPPER_ARM_LENGTH + FOREARM_LENGTH + WRIST_LENGTH, 0.0, COLUMN_TOP_Z)

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


def _box(length, width, height, center=(0, 0, 0)):
    return Pos(*center) * Box(length, width, height,
                              align=(Align.CENTER, Align.CENTER, Align.CENTER))


# --------------------------------------------------------------------------- #
# Parts
# --------------------------------------------------------------------------- #


def make_base() -> Compound:
    """Mounting base + plinth. Static (no animation)."""
    plinth = Pos(0, 0, BASE_H / 2) * Cylinder(BASE_R, BASE_H,
        align=(Align.CENTER, Align.CENTER, Align.CENTER))
    ground = Pos(0, 0, 5) * Box(BASE_R * 2.2, BASE_R * 2.2, 10,
        align=(Align.CENTER, Align.CENTER, Align.CENTER))
    return _compound_of((plinth, ground), label="base")


def make_column() -> Compound:
    """Yaw column (J0 turns this). From top of base to J1 pivot."""
    bottom_z = BASE_H
    body = _cyl_along("Z", COLUMN_R, COLUMN_TOP_Z - bottom_z,
                      center=(0, 0, (bottom_z + COLUMN_TOP_Z) / 2))
    # J1 yoke - a torus-like ring at the top so the pivot reads
    yoke = _cyl_along("Y", COLUMN_R + 5, COLUMN_R * 1.6,
                      center=(0, 0, COLUMN_TOP_Z))
    return _compound_of((body, yoke), label="column")


def make_upper_arm() -> Compound:
    """Link from J1 to J2 (200 mm horizontal). Rotates around J1 axis +Y."""
    mid = ((J1[0] + J2[0]) / 2, 0, J1[2])
    body = _box(UPPER_ARM_LENGTH, UPPER_ARM_W, UPPER_ARM_H, center=mid)
    # End discs at each joint for a robotic look
    j1_disc = _cyl_along("Y", UPPER_ARM_H / 2 + 6, UPPER_ARM_W + 8, center=J1)
    j2_disc = _cyl_along("Y", UPPER_ARM_H / 2 + 4, UPPER_ARM_W + 4, center=J2)
    return _compound_of((body, j1_disc, j2_disc), label="upper_arm")


def make_forearm() -> Compound:
    mid = ((J2[0] + J3[0]) / 2, 0, J1[2])
    body = _box(FOREARM_LENGTH, FOREARM_W, FOREARM_H, center=mid)
    j3_disc = _cyl_along("Y", FOREARM_H / 2 + 4, FOREARM_W + 4, center=J3)
    return _compound_of((body, j3_disc), label="forearm")


def make_wrist() -> Compound:
    mid = ((J3[0] + J4[0]) / 2, 0, J1[2])
    body = _box(WRIST_LENGTH, WRIST_W, WRIST_H, center=mid)
    j4_disc = _cyl_along("X", WRIST_H / 2 + 4, 24, center=J4)
    return _compound_of((body, j4_disc), label="wrist")


def make_gripper_base() -> Compound:
    """Tool plate that turns with J4 (X-axis roll). Carries the two fingers
    via separate `gripper_left` / `gripper_right` parts so they can open."""
    plate_center = (J4[0] + GRIPPER_BASE_OFFSET, 0, J1[2])
    plate = _cyl_along("X", WRIST_H / 2 + 8, GRIPPER_PLATE_T, center=plate_center)
    return _compound_of((plate,), label="gripper_base")


def make_gripper_finger(side: str) -> Compound:
    """One jaw of the parallel-jaw gripper, modeled at half-open pose so the
    sidecar can both close (negative offset) and open (positive)."""
    sign = +1.0 if side == "left" else -1.0
    y_off = sign * (GRIPPER_FINGER_W / 2 + 10.0)
    x_center = J4[0] + GRIPPER_BASE_OFFSET + GRIPPER_PLATE_T / 2 + GRIPPER_FINGER_L / 2
    body = _box(GRIPPER_FINGER_L, GRIPPER_FINGER_W, GRIPPER_FINGER_H,
                center=(x_center, y_off, J1[2]))
    # Tip pad
    pad = _box(20, GRIPPER_FINGER_W, GRIPPER_FINGER_H + 4,
               center=(x_center + GRIPPER_FINGER_L / 2 - 10, y_off - sign * 4, J1[2]))
    return _compound_of((body, pad), label=f"gripper_{side}")


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def gen_step() -> Compound:
    children = [
        make_base(),              # o1.1
        make_column(),            # o1.2  (yaw J0)
        make_upper_arm(),         # o1.3  (J0 + J1)
        make_forearm(),           # o1.4  (J0 + J1 + J2)
        make_wrist(),             # o1.5  (J0 + J1 + J2 + J3)
        make_gripper_base(),      # o1.6  (J0..J3 + J4)
        make_gripper_finger("left"),   # o1.7  (full chain + open offset)
        make_gripper_finger("right"),  # o1.8
    ]
    return Compound(label="robot_arm", children=children)


if __name__ == "__main__":
    arm = gen_step()
    print(f"children: {len(arm.children)}")
    for i, c in enumerate(arm.children, start=1):
        print(f"  o1.{i}: {c.label}")
