"""Road bicycle, parameterized, with a cut-away cassette so the drivetrain
is visible from outside.

Units: millimeters.
Convention: +X forward, +Y left, +Z up. Origin at the midpoint between the
two wheel/ground contact patches on the ground plane.

This is a teaching aid for the "forward motion" principle:
  rider pushes pedal -> crank arm + chainring rotate around the bottom
  bracket -> chain transfers rotation to the rear cog -> rear cog spins
  the rear wheel -> rolling friction makes the bike roll forward; the
  front wheel rolls along.

The .bicycle.step.js sidecar drives the animation. The order of children
in the returned Compound defines occurrence ids (o1.1, o1.2 ...); the
sidecar references parts by those ids, so do not reorder children
without updating the sidecar.
"""

from __future__ import annotations

import math
from typing import Iterable

from build123d import (
    Align,
    Axis,
    Box,
    Cylinder,
    Compound,
    Location,
    Plane,
    Pos,
    Rot,
    Solid,
    Sphere,
    Torus,
    Vector,
)

# --------------------------------------------------------------------------- #
# Parameters - road bike geometry (54 cm frame, 700c)
# --------------------------------------------------------------------------- #
WHEELBASE = 1010.0
WHEEL_RADIUS = 350.0          # 700c outer (tyre)
RIM_RADIUS = 320.0
RIM_WIDTH = 24.0
TYRE_WIDTH = 32.0
HUB_RADIUS = 22.0
HUB_LENGTH = 100.0
SPOKE_RADIUS = 1.6
SPOKES_PER_WHEEL = 16

# Wheel contact patches on the ground:
FRONT_CONTACT_X = WHEELBASE / 2
REAR_CONTACT_X = -WHEELBASE / 2
FRONT_HUB = (FRONT_CONTACT_X, 0.0, WHEEL_RADIUS)
REAR_HUB = (REAR_CONTACT_X, 0.0, WHEEL_RADIUS)

# Bottom bracket: chainstay 410 mm long, BB drop 70 mm.
CHAINSTAY_LENGTH = 410.0
BB_DROP = 70.0
BB_Z = WHEEL_RADIUS - BB_DROP
_dx = math.sqrt(CHAINSTAY_LENGTH ** 2 - BB_DROP ** 2)
BB = (REAR_CONTACT_X + _dx, 0.0, BB_Z)         # (-101.4, 0, 280)
BB_SHELL_R = 22.0
BB_SHELL_LEN = 70.0

# Seat tube
SEAT_TUBE_ANGLE_DEG = 73.0
SEAT_TUBE_LENGTH = 540.0
_st_dir = (-math.cos(math.radians(SEAT_TUBE_ANGLE_DEG)),
           0.0,
           math.sin(math.radians(SEAT_TUBE_ANGLE_DEG)))
SEAT_TUBE_TOP = (BB[0] + SEAT_TUBE_LENGTH * _st_dir[0],
                 0.0,
                 BB[2] + SEAT_TUBE_LENGTH * _st_dir[2])  # ~(-259, 0, 796)

# Top tube: horizontal forward 540 mm
TOP_TUBE_LENGTH = 540.0
HEAD_TUBE_TOP = (SEAT_TUBE_TOP[0] + TOP_TUBE_LENGTH, 0.0, SEAT_TUBE_TOP[2])

# Head tube: 73 deg from horizontal, 150 mm long, going down/forward
HEAD_TUBE_ANGLE_DEG = 73.0
HEAD_TUBE_LENGTH = 150.0
_ht_dir = (math.cos(math.radians(HEAD_TUBE_ANGLE_DEG)),
           0.0,
           -math.sin(math.radians(HEAD_TUBE_ANGLE_DEG)))
HEAD_TUBE_BOTTOM = (HEAD_TUBE_TOP[0] + HEAD_TUBE_LENGTH * _ht_dir[0],
                    0.0,
                    HEAD_TUBE_TOP[2] + HEAD_TUBE_LENGTH * _ht_dir[2])

# Tube radii
DOWN_TUBE_R = 18.0
TOP_TUBE_R = 14.0
SEAT_TUBE_R = 15.0
HEAD_TUBE_R = 19.0
STAY_R = 9.0          # chainstays / seatstays
FORK_R = 11.0

# Drivetrain
CRANK_LENGTH = 170.0
CRANK_THICK = 14.0
CRANK_WIDTH = 32.0
CHAINRING_R = 95.0
CHAINRING_THICK = 6.0
COG_R = 38.0
COG_THICK = 6.0
PEDAL_BODY = (95.0, 75.0, 16.0)   # length x depth x thickness
PEDAL_OFFSET_Y_L = 75.0            # left pedal is outboard +Y from BB centerline
PEDAL_OFFSET_Y_R = -75.0
CHAIN_PLANE_Y = -50.0              # chain runs on the right (-Y) side
CHAIN_THICK = 6.0
CHAIN_WIDTH = 7.5

# Handlebar / saddle
STEM_LENGTH = 110.0
HANDLEBAR_WIDTH = 440.0
HANDLEBAR_DROP = 130.0
HANDLEBAR_R = 11.0
SADDLE_LENGTH = 260.0
SADDLE_WIDTH = 145.0
SADDLE_THICK = 28.0
SEATPOST_LENGTH = 240.0
SEATPOST_R = 13.0

# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #


def _vec(p) -> Vector:
    return p if isinstance(p, Vector) else Vector(*p)


def _tube_between(p1, p2, radius: float) -> Solid:
    """Cylinder of given radius oriented from p1 to p2."""
    p1v = _vec(p1)
    p2v = _vec(p2)
    diff = p2v - p1v
    length = diff.length
    if length < 1e-6:
        return Cylinder(radius, 0.1, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    direction = (diff * (1.0 / length))
    midpoint = (p1v + p2v) * 0.5
    plane = Plane(origin=midpoint, z_dir=direction)
    return plane * Cylinder(radius, length,
                            align=(Align.CENTER, Align.CENTER, Align.CENTER))


def _cyl_along(axis: str, radius: float, length: float, center=(0, 0, 0)) -> Solid:
    base = Cylinder(radius, length, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    if axis.upper() == "X":
        base = Rot(0, 90, 0) * base
    elif axis.upper() == "Y":
        base = Rot(90, 0, 0) * base
    return Pos(*center) * base


def _fuse(parts: Iterable[Solid]) -> Solid:
    parts = list(parts)
    result = parts[0]
    for other in parts[1:]:
        result = result + other
    return result


# --------------------------------------------------------------------------- #
# Wheel
# --------------------------------------------------------------------------- #


def _make_spokes() -> Solid:
    """16 thin radial spokes alternating between left and right hub flanges."""
    spokes = []
    for i in range(SPOKES_PER_WHEEL):
        theta = (2 * math.pi * i) / SPOKES_PER_WHEEL
        # Hub end is offset in Y, rim end is in plane Y=0
        y_hub = HUB_LENGTH / 2 - 12 if i % 2 == 0 else -(HUB_LENGTH / 2 - 12)
        hub_end = (HUB_RADIUS * math.cos(theta), y_hub,
                   WHEEL_RADIUS + HUB_RADIUS * math.sin(theta) - WHEEL_RADIUS)
        # Rim end at radius=RIM_RADIUS-RIM_WIDTH/2
        rim_r = RIM_RADIUS - RIM_WIDTH / 2 - 2
        rim_end = (rim_r * math.cos(theta), 0.0, rim_r * math.sin(theta))
        spokes.append(_tube_between(hub_end, rim_end, SPOKE_RADIUS))
    return _fuse(spokes)


def _to_solids(piece) -> list[Solid]:
    """Flatten anything (Solid, Compound, ShapeList) into a list of Solids."""
    if isinstance(piece, Solid):
        return [piece]
    if isinstance(piece, Compound):
        return list(piece.solids())
    if hasattr(piece, "__iter__"):
        flat: list[Solid] = []
        for item in piece:
            flat.extend(_to_solids(item))
        return flat
    return [piece]


def _compound_of(pieces, label: str | None = None) -> Compound:
    """Build a labeled Compound from any mix of Solid / Compound / ShapeList."""
    solids: list[Solid] = []
    for piece in pieces:
        solids.extend(_to_solids(piece))
    body = Compound(label=label or "", children=solids)
    if label:
        body.label = label
    return body


def make_wheel(center_x: float, label: str) -> Compound:
    """Build one wheel: tyre + rim + hub + spokes, centered at (center_x, 0, R)
    with the axle running along Y. Returned as one labeled Compound so the
    sidecar can transform it as a single rigid body via #o1.N.
    """
    tyre = Torus(major_radius=WHEEL_RADIUS - TYRE_WIDTH / 2,
                 minor_radius=TYRE_WIDTH / 2)
    tyre = Rot(90, 0, 0) * tyre  # axis along Y
    rim_outer = Cylinder(RIM_RADIUS, RIM_WIDTH,
                         align=(Align.CENTER, Align.CENTER, Align.CENTER))
    rim_inner = Cylinder(RIM_RADIUS - 18, RIM_WIDTH + 2,
                         align=(Align.CENTER, Align.CENTER, Align.CENTER))
    rim = rim_outer - rim_inner
    rim = Rot(90, 0, 0) * rim
    hub = Cylinder(HUB_RADIUS, HUB_LENGTH,
                   align=(Align.CENTER, Align.CENTER, Align.CENTER))
    hub = Rot(90, 0, 0) * hub
    spokes = _make_spokes()
    wheel_local = _compound_of((tyre, rim, hub, spokes))
    moved = wheel_local.moved(Location((center_x, 0, WHEEL_RADIUS)))
    moved.label = label
    return moved


# --------------------------------------------------------------------------- #
# Frame
# --------------------------------------------------------------------------- #


def make_frame() -> Compound:
    bb_shell = _cyl_along("Y", BB_SHELL_R, BB_SHELL_LEN, center=BB)
    head_tube = _tube_between(
        (HEAD_TUBE_BOTTOM[0] - 5, 0, HEAD_TUBE_BOTTOM[2] - 5),
        (HEAD_TUBE_TOP[0] + 5, 0, HEAD_TUBE_TOP[2] + 5),
        HEAD_TUBE_R,
    )
    down_tube = _tube_between(HEAD_TUBE_BOTTOM, BB, DOWN_TUBE_R)
    top_tube = _tube_between(HEAD_TUBE_TOP, SEAT_TUBE_TOP, TOP_TUBE_R)
    seat_tube = _tube_between(BB, (SEAT_TUBE_TOP[0], 0, SEAT_TUBE_TOP[2] + 40),
                              SEAT_TUBE_R)
    stay_offset = 45.0
    rear_hub_l = (REAR_CONTACT_X, +stay_offset, WHEEL_RADIUS)
    rear_hub_r = (REAR_CONTACT_X, -stay_offset, WHEEL_RADIUS)
    bb_l = (BB[0], +stay_offset / 2, BB[2])
    bb_r = (BB[0], -stay_offset / 2, BB[2])
    chainstay_l = _tube_between(bb_l, rear_hub_l, STAY_R)
    chainstay_r = _tube_between(bb_r, rear_hub_r, STAY_R)
    st_top_l = (SEAT_TUBE_TOP[0], +20, SEAT_TUBE_TOP[2] - 30)
    st_top_r = (SEAT_TUBE_TOP[0], -20, SEAT_TUBE_TOP[2] - 30)
    seatstay_l = _tube_between(st_top_l, rear_hub_l, STAY_R)
    seatstay_r = _tube_between(st_top_r, rear_hub_r, STAY_R)
    return _compound_of(
        (bb_shell, head_tube, down_tube, top_tube, seat_tube,
         chainstay_l, chainstay_r, seatstay_l, seatstay_r),
        label="frame",
    )


def make_fork() -> Compound:
    crown = (HEAD_TUBE_BOTTOM[0], 0, HEAD_TUBE_BOTTOM[2])
    fork_l = _tube_between(crown, (FRONT_HUB[0], +45, FRONT_HUB[2]), FORK_R)
    fork_r = _tube_between(crown, (FRONT_HUB[0], -45, FRONT_HUB[2]), FORK_R)
    steerer = _tube_between(crown,
                            (HEAD_TUBE_TOP[0], 0, HEAD_TUBE_TOP[2] + 20),
                            FORK_R)
    return _compound_of((fork_l, fork_r, steerer), label="fork")


def make_handlebar_stem() -> Compound:
    stem_start = (HEAD_TUBE_TOP[0] + 15, 0, HEAD_TUBE_TOP[2] + 25)
    stem_end = (stem_start[0] + STEM_LENGTH, 0, stem_start[2] + 5)
    stem = _tube_between(stem_start, stem_end, 13.0)
    bar_y = HANDLEBAR_WIDTH / 2
    bar_top_l = (stem_end[0], +bar_y, stem_end[2])
    bar_top_r = (stem_end[0], -bar_y, stem_end[2])
    top_bar = _tube_between(bar_top_l, bar_top_r, HANDLEBAR_R)
    drop_l_curve = _tube_between(
        bar_top_l,
        (bar_top_l[0] + 70, bar_top_l[1], bar_top_l[2] - 40),
        HANDLEBAR_R,
    )
    drop_l_down = _tube_between(
        (bar_top_l[0] + 70, bar_top_l[1], bar_top_l[2] - 40),
        (bar_top_l[0] + 50, bar_top_l[1], bar_top_l[2] - HANDLEBAR_DROP),
        HANDLEBAR_R,
    )
    drop_r_curve = _tube_between(
        bar_top_r,
        (bar_top_r[0] + 70, bar_top_r[1], bar_top_r[2] - 40),
        HANDLEBAR_R,
    )
    drop_r_down = _tube_between(
        (bar_top_r[0] + 70, bar_top_r[1], bar_top_r[2] - 40),
        (bar_top_r[0] + 50, bar_top_r[1], bar_top_r[2] - HANDLEBAR_DROP),
        HANDLEBAR_R,
    )
    return _compound_of(
        (stem, top_bar, drop_l_curve, drop_l_down, drop_r_curve, drop_r_down),
        label="handlebar_stem",
    )


def make_seatpost_saddle() -> Compound:
    seatpost_top = (SEAT_TUBE_TOP[0] - 60, 0, SEAT_TUBE_TOP[2] + SEATPOST_LENGTH)
    seatpost = _tube_between(SEAT_TUBE_TOP, seatpost_top, SEATPOST_R)
    saddle_center = (seatpost_top[0], 0, seatpost_top[2] + SADDLE_THICK / 2 + 5)
    saddle = Pos(*saddle_center) * Box(SADDLE_LENGTH, SADDLE_WIDTH, SADDLE_THICK,
                                       align=(Align.CENTER, Align.CENTER, Align.CENTER))
    return _compound_of((seatpost, saddle), label="seatpost_saddle")


# --------------------------------------------------------------------------- #
# Drivetrain
# --------------------------------------------------------------------------- #


def make_crank_arm(side: str) -> Compound:
    """Crank arm at the static pose (left arm pointing -Z down, right arm
    pointing +Z up). The sidecar rotates them around BB."""
    y_inboard = +BB_SHELL_LEN / 2 + 8 if side == "left" else -BB_SHELL_LEN / 2 - 8
    y_outboard = +PEDAL_OFFSET_Y_L if side == "left" else PEDAL_OFFSET_Y_R
    z_at_bb = BB[2]
    z_at_pedal = BB[2] - CRANK_LENGTH if side == "left" else BB[2] + CRANK_LENGTH

    mid_z = (z_at_bb + z_at_pedal) / 2
    arm_length_z = abs(z_at_pedal - z_at_bb)
    arm = Pos(BB[0], (y_inboard + y_outboard) / 2, mid_z) * Box(
        CRANK_THICK,
        abs(y_outboard - y_inboard) + 8,
        arm_length_z + 20,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    hub_disc = _cyl_along("Y", 24, abs(y_outboard - y_inboard) + 4,
                          center=(BB[0], (y_inboard + y_outboard) / 2, z_at_bb))
    pedal_disc = _cyl_along("Y", 16, 24,
                            center=(BB[0], y_outboard, z_at_pedal))
    return _compound_of((arm, hub_disc, pedal_disc), label=f"crank_{side}")


def make_pedal(side: str) -> Compound:
    """Pedal modeled at its TDC/BDC position aligned with the crank arm.
    The sidecar translates it each frame to follow the rotating crank pin."""
    y_outboard = PEDAL_OFFSET_Y_L if side == "left" else PEDAL_OFFSET_Y_R
    z_pedal = BB[2] - CRANK_LENGTH if side == "left" else BB[2] + CRANK_LENGTH
    body = Pos(BB[0], y_outboard, z_pedal) * Box(
        PEDAL_BODY[0], PEDAL_BODY[1], PEDAL_BODY[2],
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    return _compound_of((body,), label=f"pedal_{side}")


def make_chainring() -> Compound:
    """Chainring on the right side (-Y), centered on BB axis."""
    disc = _cyl_along("Y", CHAINRING_R, CHAINRING_THICK,
                      center=(BB[0], -BB_SHELL_LEN / 2 - 10, BB[2]))
    body = disc
    for i in range(5):
        ang = i * (2 * math.pi / 5) + math.pi / 5
        hx = BB[0] + CHAINRING_R * 0.55 * math.cos(ang)
        hz = BB[2] + CHAINRING_R * 0.55 * math.sin(ang)
        hole = _cyl_along("Y", 16, CHAINRING_THICK + 4,
                          center=(hx, -BB_SHELL_LEN / 2 - 10, hz))
        body = body - hole
    return _compound_of((body,), label="chainring")


def make_rear_cog() -> Compound:
    disc = _cyl_along("Y", COG_R, COG_THICK,
                      center=(REAR_CONTACT_X, -45 + 4, WHEEL_RADIUS))
    notch = Pos(REAR_CONTACT_X, -45 + 4, WHEEL_RADIUS + COG_R * 0.7) * Box(
        COG_R * 0.4, COG_THICK + 4, COG_R * 0.5,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    body = disc - notch
    return _compound_of((body,), label="rear_cog")


def make_chain() -> Compound:
    """Simplified chain: two parallel rounded segments between chainring and
    cog tangent points. Static visual link, not animated."""
    chain_y = -BB_SHELL_LEN / 2 - 10 + (CHAINRING_THICK / 2) + 1
    chainring_top = (BB[0], chain_y, BB[2] + CHAINRING_R)
    cog_top = (REAR_CONTACT_X, chain_y, WHEEL_RADIUS + COG_R)
    top_run = _tube_between(chainring_top, cog_top, CHAIN_WIDTH / 2)
    chainring_bot = (BB[0], chain_y, BB[2] - CHAINRING_R)
    cog_bot = (REAR_CONTACT_X, chain_y, WHEEL_RADIUS - COG_R)
    bot_run = _tube_between(chainring_bot, cog_bot, CHAIN_WIDTH / 2)
    return _compound_of((top_run, bot_run), label="chain")


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def gen_step() -> Compound:
    children = [
        make_frame(),                            # o1.1
        make_fork(),                             # o1.2
        make_handlebar_stem(),                   # o1.3
        make_seatpost_saddle(),                  # o1.4
        make_wheel(FRONT_CONTACT_X, "wheel_front"),  # o1.5
        make_wheel(REAR_CONTACT_X, "wheel_rear"),    # o1.6
        make_crank_arm("left"),                  # o1.7
        make_crank_arm("right"),                 # o1.8
        make_pedal("left"),                      # o1.9
        make_pedal("right"),                     # o1.10
        make_chainring(),                        # o1.11
        make_rear_cog(),                         # o1.12
        make_chain(),                            # o1.13
    ]
    bike = Compound(label="bicycle", children=children)
    return bike


if __name__ == "__main__":
    bike = gen_step()
    print(f"children: {len(bike.children)}")
    for i, c in enumerate(bike.children, start=1):
        print(f"  o1.{i}: {c.label}")
