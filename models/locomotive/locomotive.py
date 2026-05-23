"""Steam locomotive drive train — the iconic side-rod mechanism.

Units: millimeters. +X forward, +Y left, +Z up. Origin between the
middle pair of drive wheels at ground level.

The body, boiler and cab are static stage decoration. The drive train
is the star: three drive wheels per side share a long side rod, while
the main rod converts piston reciprocation into wheel rotation. All
wheels rotate in unison; the side rod simply orbits in a circle without
tilting. The piston travel is solved with the crank-slider equation
from the main wheel's crank pin.

Sidecar reads `crank` (deg) and animates everything from it.
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
# Layout (mm) - mirrored on -Y for the right-hand side of the locomotive.
# --------------------------------------------------------------------------- #
TRACK = 720.0                       # rail gauge (Y extent of wheels)
WHEEL_R = 380.0
WHEEL_W = 80.0
WHEEL_HUB_R = 50.0

# Three drive wheels per side, evenly spaced along X.
WHEEL_X = [-900.0, 0.0, 900.0]
MAIN_WHEEL_X = 900.0                # front-most wheel drives the rod
WHEEL_Z = WHEEL_R                    # axles at WHEEL_R above ground

# Crank pins outboard of the wheel face, at radius R_CRANK from axle.
CRANK_R = 130.0
CRANK_PIN_RADIUS = 28.0
CRANK_PIN_LENGTH = 70.0
SIDE_ROD_THICK = 30.0
SIDE_ROD_WIDTH = 45.0

# Cylinder + piston in front of the front wheel
CYLINDER_LENGTH = 460.0
CYLINDER_R = 70.0
CYLINDER_CENTER_X = MAIN_WHEEL_X + 850.0   # 850 mm in front of main wheel hub
PISTON_R = 56.0
# PISTON_LENGTH is defined below where MAIN_ROD_LENGTH is computed.

# Main rod (piston to crank pin) length, chosen so the rod's small end lands
# on the piston's back face at the static crank=0 pose:
#   small_end_x  = CYLINDER_CENTER_X - PISTON_LENGTH/2
#   big_end_x    = MAIN_WHEEL_X + CRANK_R
PISTON_LENGTH = 60.0
MAIN_ROD_LENGTH = (CYLINDER_CENTER_X - PISTON_LENGTH / 2) - (MAIN_WHEEL_X + CRANK_R)

# Side rod Y offset (just outboard of the crank pin face)
ROD_Y_OFFSET = TRACK / 2 + CRANK_PIN_LENGTH / 2 + 5.0

# Boiler + cab + frame (static dressing)
BOILER_R = 280.0
BOILER_LENGTH = 2400.0
BOILER_X_CENTER = -100.0
BOILER_Z = WHEEL_R + 240.0
CAB_LENGTH = 700.0
CAB_HEIGHT = 600.0
CAB_X_CENTER = -1600.0
CAB_Z = WHEEL_R + 200.0
FRAME_LENGTH = 3000.0
FRAME_W = TRACK
FRAME_H = 60.0
FRAME_Z = WHEEL_R - 80.0
FUNNEL_R = 80.0
FUNNEL_H = 200.0
FUNNEL_X = +1300.0

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
# Static dressing
# --------------------------------------------------------------------------- #


def make_frame() -> Compound:
    body = _box(FRAME_LENGTH, FRAME_W + 40, FRAME_H,
                center=(0, 0, FRAME_Z))
    return _compound_of((body,), label="frame")


def make_boiler() -> Compound:
    body = _cyl_along("X", BOILER_R, BOILER_LENGTH,
                      center=(BOILER_X_CENTER, 0, BOILER_Z))
    funnel = _cyl_along("Z", FUNNEL_R, FUNNEL_H,
                        center=(FUNNEL_X, 0, BOILER_Z + BOILER_R + FUNNEL_H / 2 - 20))
    dome = Pos(+200, 0, BOILER_Z + BOILER_R - 10) * Sphere(140)
    return _compound_of((body, funnel, dome), label="boiler")


def make_cab() -> Compound:
    body = _box(CAB_LENGTH, BOILER_R * 2 + 60, CAB_HEIGHT,
                center=(CAB_X_CENTER, 0, CAB_Z))
    roof = _box(CAB_LENGTH + 60, BOILER_R * 2 + 100, 40,
                center=(CAB_X_CENTER, 0, CAB_Z + CAB_HEIGHT / 2 + 20))
    return _compound_of((body, roof), label="cab")


def make_cowcatcher() -> Compound:
    """Pointed pilot at the front."""
    body = _box(360, FRAME_W, 200,
                center=(FRAME_LENGTH / 2 + 100, 0, FRAME_Z + 100))
    return _compound_of((body,), label="cowcatcher")


# --------------------------------------------------------------------------- #
# Drive train (animated)
# --------------------------------------------------------------------------- #


def _spokes_for_wheel(x_center: float, y_face: float) -> list[Solid]:
    """6 thick spokes inside each wheel disc so rotation reads at a glance."""
    spokes = []
    for i in range(6):
        ang = i * math.pi / 6  # 30 deg spacing - 6 spokes spread across 180 deg
        # Use full 360 deg
        ang = i * math.pi / 3
        dx = (WHEEL_R - 30) * math.cos(ang)
        dz = (WHEEL_R - 30) * math.sin(ang)
        spoke = Pos(x_center + dx / 2, y_face, WHEEL_Z + dz / 2) * Box(
            math.hypot(dx, dz) + 20, 20, 25,
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )
        # Rotate around Y to align with the spoke direction
        spokes.append(spoke)
    # That isn't aligned correctly without rotation. Easier: keep wheel as a
    # rim + hub + a single "spoke disc" with cut-outs. Use a simpler approach:
    return []


def make_wheel(x: float, y_side: float, label: str) -> Compound:
    """Drive wheel with a flange, rim, hub, and a single crank web that lets
    the audience see the wheel rotate. The crank pin is a separate part so
    the side rod can attach to it visually."""
    # Tyre / rim: short cylinder along Y
    tyre = _cyl_along("Y", WHEEL_R, WHEEL_W, center=(x, y_side, WHEEL_Z))
    # Hub at the axle
    hub = _cyl_along("Y", WHEEL_HUB_R, WHEEL_W + 6, center=(x, y_side, WHEEL_Z))
    # Two cosmetic "counterweight" cut-outs so rotation is obvious
    cw_outer = _cyl_along("Y", WHEEL_R - 40, WHEEL_W + 0.1,
                          center=(x, y_side, WHEEL_Z))
    cw_inner = _cyl_along("Y", WHEEL_HUB_R + 20, WHEEL_W + 0.2,
                          center=(x, y_side, WHEEL_Z))
    annulus = cw_outer - cw_inner

    # 6 radial cut-outs in the annulus (spoke gaps)
    for i in range(6):
        ang = i * math.pi / 3
        cx = x + (WHEEL_R - 60) * 0.5 * math.cos(ang) * 0.0  # leave centered
        cz = WHEEL_Z + 0
        # A pie-wedge would be ideal; use a long thin slot rotated.
        # Cheap approximation: subtract two pin holes between spokes
        if i % 2 == 0:
            hole = Pos(x + (WHEEL_R - 80) * math.cos(ang),
                       y_side,
                       WHEEL_Z + (WHEEL_R - 80) * math.sin(ang)) * Cylinder(
                28, WHEEL_W + 0.5,
                align=(Align.CENTER, Align.CENTER, Align.CENTER))
            hole = Rot(90, 0, 0) * hole
            annulus = annulus - Pos(0, 0, 0) * hole
    # Crank web: a small disc offset outboard so the pin attaches to it
    web = _cyl_along("Y", CRANK_R + 30, 30,
                     center=(x, y_side + (WHEEL_W / 2 + 15) * math.copysign(1, y_side or 1), WHEEL_Z))
    return _compound_of((tyre, hub, annulus, web), label=label)


def make_crank_pin(x: float, y_side: float, label: str) -> Compound:
    """Crank pin sticking outboard from the wheel face at (x + CRANK_R, ...)
    when at the static pose (crank=0)."""
    sign = +1.0 if y_side > 0 else -1.0
    y_center = y_side + sign * (WHEEL_W / 2 + 25)
    body = _cyl_along("Y", CRANK_PIN_RADIUS, CRANK_PIN_LENGTH,
                      center=(x + CRANK_R, y_center, WHEEL_Z))
    return _compound_of((body,), label=label)


def make_side_rod(y_side: float, label: str) -> Compound:
    """Long rod across all three crank pins on one side, at the static
    pose."""
    sign = +1.0 if y_side > 0 else -1.0
    y_center = y_side + sign * (WHEEL_W / 2 + 25)
    x_min = WHEEL_X[0] + CRANK_R
    x_max = WHEEL_X[-1] + CRANK_R
    rod_length = x_max - x_min
    body = _box(rod_length + 90, SIDE_ROD_WIDTH, SIDE_ROD_THICK,
                center=((x_min + x_max) / 2, y_center, WHEEL_Z))
    # End knuckles
    knuckles = []
    for x in WHEEL_X:
        knuckles.append(_cyl_along("Y", SIDE_ROD_THICK,
                                   SIDE_ROD_WIDTH * 1.1,
                                   center=(x + CRANK_R, y_center, WHEEL_Z)))
    return _compound_of((body, *knuckles), label=label)


def make_main_rod(y_side: float, label: str) -> Compound:
    """Connecting rod from main wheel's crank pin to the piston crosshead.
    Modeled straight at crank=0, sidecar tilts and translates it."""
    sign = +1.0 if y_side > 0 else -1.0
    y_center = y_side + sign * (WHEEL_W / 2 + 25)
    big_end_x = MAIN_WHEEL_X + CRANK_R
    small_end_x = big_end_x + MAIN_ROD_LENGTH
    body = _box(MAIN_ROD_LENGTH + 80, SIDE_ROD_WIDTH * 0.85, SIDE_ROD_THICK,
                center=((big_end_x + small_end_x) / 2, y_center, WHEEL_Z))
    big = _cyl_along("Y", SIDE_ROD_THICK * 1.1, SIDE_ROD_WIDTH,
                     center=(big_end_x, y_center, WHEEL_Z))
    small = _cyl_along("Y", SIDE_ROD_THICK * 0.9, SIDE_ROD_WIDTH * 0.9,
                       center=(small_end_x, y_center, WHEEL_Z))
    return _compound_of((body, big, small), label=label)


def make_cylinder(y_side: float, label: str) -> Compound:
    """Static cylinder block. Halved on the inboard side so the piston is
    visible from outside the locomotive."""
    sign = +1.0 if y_side > 0 else -1.0
    y_center = y_side + sign * (WHEEL_W / 2 + 25)
    block = _box(CYLINDER_LENGTH + 60, 180, 200,
                 center=(CYLINDER_CENTER_X, y_center, WHEEL_Z))
    # Bore (through the inboard face)
    bore = _cyl_along("X", PISTON_R + 4, CYLINDER_LENGTH + 100,
                      center=(CYLINDER_CENTER_X, y_center, WHEEL_Z))
    body = block - bore
    return _compound_of((body,), label=label)


def make_piston(y_side: float, label: str) -> Compound:
    """Piston disc modeled at the cylinder center (mid-stroke equivalent).
    Sidecar translates it along +X using the crank-slider equation."""
    sign = +1.0 if y_side > 0 else -1.0
    y_center = y_side + sign * (WHEEL_W / 2 + 25)
    body = _cyl_along("X", PISTON_R, PISTON_LENGTH,
                      center=(CYLINDER_CENTER_X, y_center, WHEEL_Z))
    return _compound_of((body,), label=label)


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def gen_step() -> Compound:
    children = []
    # ---- Static dressing ----
    children.append(make_frame())           # o1.1
    children.append(make_boiler())          # o1.2
    children.append(make_cab())             # o1.3
    children.append(make_cowcatcher())      # o1.4

    # ---- Wheels (6 total = 3 per side) ----
    side_l = +TRACK / 2
    side_r = -TRACK / 2
    children.append(make_wheel(WHEEL_X[0], side_l, "wheel_rl"))  # o1.5
    children.append(make_wheel(WHEEL_X[1], side_l, "wheel_ml"))  # o1.6
    children.append(make_wheel(WHEEL_X[2], side_l, "wheel_fl"))  # o1.7
    children.append(make_wheel(WHEEL_X[0], side_r, "wheel_rr"))  # o1.8
    children.append(make_wheel(WHEEL_X[1], side_r, "wheel_mr"))  # o1.9
    children.append(make_wheel(WHEEL_X[2], side_r, "wheel_fr"))  # o1.10

    # ---- Crank pins (one per wheel on each side) ----
    for i, x in enumerate(WHEEL_X, start=1):
        children.append(make_crank_pin(x, side_l, f"pin_l_{i}"))   # o1.11..13
    for i, x in enumerate(WHEEL_X, start=1):
        children.append(make_crank_pin(x, side_r, f"pin_r_{i}"))   # o1.14..16

    # ---- Side rods (one per side) ----
    children.append(make_side_rod(side_l, "side_rod_l"))           # o1.17
    children.append(make_side_rod(side_r, "side_rod_r"))           # o1.18

    # ---- Main rods + pistons + cylinders ----
    children.append(make_main_rod(side_l, "main_rod_l"))           # o1.19
    children.append(make_main_rod(side_r, "main_rod_r"))           # o1.20
    children.append(make_cylinder(side_l, "cylinder_l"))           # o1.21
    children.append(make_cylinder(side_r, "cylinder_r"))           # o1.22
    children.append(make_piston(side_l, "piston_l"))               # o1.23
    children.append(make_piston(side_r, "piston_r"))               # o1.24

    return Compound(label="locomotive", children=children)


if __name__ == "__main__":
    loco = gen_step()
    print(f"children: {len(loco.children)}")
    for i, c in enumerate(loco.children, start=1):
        print(f"  o1.{i}: {c.label}")
