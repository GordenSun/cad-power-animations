"""Folding director's chair — 4-bar scissor mechanism.

Units: millimeters. +X forward (away from the back-rest), +Y left, +Z up.
Origin between the two side-frames on the ground plane.

Each side has two crossed legs that pivot around a shared hinge pin.
The sidecar rotates the legs by `fold` degrees about that hinge so the
audience can watch the X close, and exposes a `hinge_position` slider
(0..1, fraction along the leg) that visually slides the pivot up or down
the legs. With the hinge at the midpoint the chair folds symmetrically;
move it off-centre and you can see the legs swing through different arcs
and end up at a different folded volume.
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
    Vector,
)

# --------------------------------------------------------------------------- #
# Geometry constants - mirrored exactly in the .step.js sidecar.
# --------------------------------------------------------------------------- #
LEG_R = 13.0
LEG_SPREAD_X = 200.0                          # half X-distance between leg ground contacts
LEG_TOP_Z = 480.0                             # height of seat top in open pose
LEG_LENGTH = math.hypot(2 * LEG_SPREAD_X, LEG_TOP_Z)  # ~620 mm
SIDE_Y = 220.0                                # half-spacing between left and right frames

# Hinge pin (visible bolt) at the centre of the X in the open pose
HINGE_DEFAULT_Z = LEG_TOP_Z * 0.5
HINGE_PIN_R = 9.0
HINGE_PIN_LENGTH = 2 * SIDE_Y + 60.0

# Seat panel
SEAT_DEPTH = 360.0
SEAT_WIDTH = 2 * SIDE_Y + 40.0
SEAT_THICK = 18.0

# Backrest (modelled at zero pose; sidecar rides it on the back-leg-top
# transform)
BACK_HEIGHT = 240.0
BACK_THICK = 18.0
BACK_WIDTH = SEAT_WIDTH

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


def _tube_between(p1, p2, radius):
    p1v = Vector(*p1)
    p2v = Vector(*p2)
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
# Leg layout (zero/open pose, viewed from +Y looking -Y):
#   Leg "a" (front_top_back_bottom):   bottom (+LEG_SPREAD_X, y, 0)  → top (-LEG_SPREAD_X, y, LEG_TOP_Z)
#   Leg "b" (front_bottom_back_top):   bottom (-LEG_SPREAD_X, y, 0)  → top (+LEG_SPREAD_X, y, LEG_TOP_Z)
# They cross exactly at (0, y, HINGE_DEFAULT_Z = LEG_TOP_Z/2).


def make_leg(side_y: float, leg_kind: str) -> Compound:
    if leg_kind == "a":
        p_bottom = (+LEG_SPREAD_X, side_y, 0)
        p_top    = (-LEG_SPREAD_X, side_y, LEG_TOP_Z)
        label = ("left" if side_y > 0 else "right") + "_leg_a"
    else:  # "b"
        p_bottom = (-LEG_SPREAD_X, side_y, 0)
        p_top    = (+LEG_SPREAD_X, side_y, LEG_TOP_Z)
        label = ("left" if side_y > 0 else "right") + "_leg_b"
    body = _tube_between(p_bottom, p_top, LEG_R)
    # Round end caps so the leg looks finished
    caps = [
        Pos(*p_bottom) * Cylinder(LEG_R, 0.1, align=(Align.CENTER, Align.CENTER, Align.CENTER)),
        Pos(*p_top)    * Cylinder(LEG_R, 0.1, align=(Align.CENTER, Align.CENTER, Align.CENTER)),
    ]
    return _compound_of((body, *caps), label=label)


def make_hinge_pin() -> Compound:
    body = _cyl_along("Y", HINGE_PIN_R, HINGE_PIN_LENGTH,
                      center=(0, 0, HINGE_DEFAULT_Z))
    return _compound_of((body,), label="hinge_pin")


def make_seat() -> Compound:
    body = Pos(0, 0, LEG_TOP_Z + SEAT_THICK / 2) * Box(
        SEAT_DEPTH, SEAT_WIDTH, SEAT_THICK,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    return _compound_of((body,), label="seat")


def make_backrest() -> Compound:
    """Sits behind the seat in the open pose. The sidecar rotates it along
    with the back-leg rotation so it always reads as 'attached to the back
    of the chair'."""
    back_x = -LEG_SPREAD_X - 30.0
    body = Pos(back_x, 0, LEG_TOP_Z + SEAT_THICK + BACK_HEIGHT / 2) * Box(
        BACK_THICK, BACK_WIDTH, BACK_HEIGHT,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    return _compound_of((body,), label="backrest")


def make_ghost_box() -> Compound:
    """A wireframe box that the sidecar resizes to highlight the folded
    envelope. Lives just outside the chair on +X for visibility."""
    box = Pos(+SEAT_DEPTH * 1.6, 0, BACK_HEIGHT) * Box(
        60.0, 60.0, 60.0,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    return _compound_of((box,), label="ghost_envelope")


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def gen_step() -> Compound:
    children = [
        make_leg(+SIDE_Y, "a"),   # o1.1 left_leg_a
        make_leg(+SIDE_Y, "b"),   # o1.2 left_leg_b
        make_leg(-SIDE_Y, "a"),   # o1.3 right_leg_a
        make_leg(-SIDE_Y, "b"),   # o1.4 right_leg_b
        make_hinge_pin(),         # o1.5
        make_seat(),              # o1.6
        make_backrest(),          # o1.7
        make_ghost_box(),         # o1.8
    ]
    return Compound(label="folding_chair", children=children)


if __name__ == "__main__":
    chair = gen_step()
    print(f"children: {len(chair.children)}")
    for i, c in enumerate(chair.children, start=1):
        print(f"  o1.{i}: {c.label}")
