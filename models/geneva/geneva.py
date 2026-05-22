"""Geneva drive — continuous rotary input drives a 4-slot driven wheel
in 90-degree intermittent steps.

Units: millimeters. Rotation axes are along +Y. Discs lie in the XZ
plane.

The driver carries one pin and a lock disc with a circular cutout. The
driven wheel has 4 radial slots and matching curved cutouts on its rim.
As the driver rotates:
  - while the pin is engaged with a slot, the driven wheel rotates 90°;
  - while the pin is disengaged, the lock disc holds the driven wheel
    stationary (the cutout aligns with the driven wheel's rim arc).
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
# Parameters (4-slot Geneva, equal radii to keep the math simple)
# --------------------------------------------------------------------------- #
N_SLOTS = 4

# The classical condition for the slot to enter perpendicular to the
# driver radius is: center distance C = R_driven * sqrt(2) for a 4-slot.
DRIVEN_RADIUS = 110.0
CENTER_DISTANCE = DRIVEN_RADIUS * math.sqrt(2)            # ≈ 155.6
DRIVER_RADIUS = math.sqrt(CENTER_DISTANCE ** 2 - DRIVEN_RADIUS ** 2)  # equal to driven

PIN_RADIUS = 10.0                # cylindrical pin on the driver
PIN_OFFSET = DRIVER_RADIUS - 5   # near the rim, just inside the slot tangent
SLOT_HALF_WIDTH = PIN_RADIUS + 1 # slot a touch wider than the pin
SLOT_DEPTH = DRIVEN_RADIUS + 5   # slot reaches past the center for visual

DISC_THICK = 25.0
HUB_RADIUS = 14.0

LOCK_OUTER = DRIVER_RADIUS - 4    # lock disc just inside the pin
LOCK_CUTOUT_RADIUS = DRIVEN_RADIUS + 3  # circular cutout to clear the driven wheel rim during the swing
LOCK_THICK = DISC_THICK            # same axial extent

DRIVER_CENTER = (0.0, 0.0, 0.0)
DRIVEN_CENTER = (CENTER_DISTANCE, 0.0, 0.0)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _to_solids(p):
    if isinstance(p, Solid): return [p]
    if isinstance(p, Compound): return list(p.solids())
    if hasattr(p, "__iter__"):
        out = []
        for it in p: out.extend(_to_solids(it))
        return out
    return [p]


def _compound_of(pieces, label=None):
    solids = []
    for p in pieces: solids.extend(_to_solids(p))
    body = Compound(label=label or "", children=solids)
    if label: body.label = label
    return body


def _cyl_along(axis, radius, length, center=(0, 0, 0)):
    base = Cylinder(radius, length, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    if axis.upper() == "X":
        base = Rot(0, 90, 0) * base
    elif axis.upper() == "Y":
        base = Rot(90, 0, 0) * base
    return Pos(*center) * base


# --------------------------------------------------------------------------- #
# Driven wheel (4-slot Maltese cross style disc)
# --------------------------------------------------------------------------- #


def make_driven_wheel() -> Compound:
    disc = _cyl_along("Y", DRIVEN_RADIUS, DISC_THICK, center=DRIVEN_CENTER)

    # Slots at 180°, 270°, 0°, 90° from driven center (one slot points
    # at the driver at the engagement instant).
    # Scallops sit between slots at 135°, 225°, 315°, 45°.
    SLOT_BASE_RAD = math.pi          # 180°
    SCALLOP_BASE_RAD = 3 * math.pi / 4   # 135°
    for i in range(N_SLOTS):
        angle = i * (2 * math.pi / N_SLOTS) + SLOT_BASE_RAD
        cx = DRIVEN_CENTER[0] + (DRIVEN_RADIUS / 2) * math.cos(angle)
        cz = DRIVEN_CENTER[2] + (DRIVEN_RADIUS / 2) * math.sin(angle)
        deg = 90.0 - math.degrees(angle)
        slot = Box(2 * SLOT_HALF_WIDTH, DISC_THICK + 2, SLOT_DEPTH,
                   align=(Align.CENTER, Align.CENTER, Align.CENTER))
        slot = Rot(0, deg, 0) * slot
        slot = Pos(cx, DRIVEN_CENTER[1], cz) * slot
        disc = disc - slot
    for i in range(N_SLOTS):
        angle = i * (2 * math.pi / N_SLOTS) + SCALLOP_BASE_RAD
        cx = DRIVEN_CENTER[0] + DRIVEN_RADIUS * math.cos(angle)
        cz = DRIVEN_CENTER[2] + DRIVEN_RADIUS * math.sin(angle)
        scallop = _cyl_along("Y", LOCK_CUTOUT_RADIUS * 0.55, DISC_THICK + 2,
                             center=(cx, DRIVEN_CENTER[1], cz))
        disc = disc - scallop

    hub = _cyl_along("Y", HUB_RADIUS, DISC_THICK + 8, center=DRIVEN_CENTER)
    return _compound_of([disc, hub], label="driven")


# --------------------------------------------------------------------------- #
# Driver pieces
# --------------------------------------------------------------------------- #


def make_driver_disc() -> Compound:
    """The crank disc that carries the pin and the lock plate."""
    disc = _cyl_along("Y", DRIVER_RADIUS, DISC_THICK, center=DRIVER_CENTER)
    hub = _cyl_along("Y", HUB_RADIUS, DISC_THICK + 8, center=DRIVER_CENTER)
    return _compound_of([disc, hub], label="driver_disc")


def make_lock_disc() -> Compound:
    """Larger plate behind the disc with one cutout so the driven wheel can
    swing through. Stays rigidly attached to the driver."""
    plate = _cyl_along("Y", LOCK_OUTER, LOCK_THICK,
                       center=(DRIVER_CENTER[0], DRIVER_CENTER[1] - DISC_THICK - 2,
                               DRIVER_CENTER[2]))
    # Cut: the chord-shaped relief facing the driven wheel (+X side).
    cutout = _cyl_along("Y", LOCK_CUTOUT_RADIUS, LOCK_THICK + 4,
                        center=(DRIVER_CENTER[0] + LOCK_OUTER + LOCK_CUTOUT_RADIUS - 30,
                                DRIVER_CENTER[1] - DISC_THICK - 2,
                                DRIVER_CENTER[2]))
    plate = plate - cutout
    return _compound_of([plate], label="lock_disc")


def make_pin() -> Compound:
    """Cylindrical pin that rides in the driven wheel's slot."""
    pin = _cyl_along("Y", PIN_RADIUS, DISC_THICK + 24,
                     center=(DRIVER_CENTER[0] + PIN_OFFSET,
                             DRIVER_CENTER[1] + 12,
                             DRIVER_CENTER[2]))
    return _compound_of([pin], label="pin")


def make_base_plate() -> Compound:
    """Compact base bracket BEHIND the discs (positive Y in CAD frame)
    so it doesn't occlude the front face when viewed from -Y."""
    Y_BACK = +DISC_THICK + 12
    plate = Pos((DRIVER_CENTER[0] + DRIVEN_CENTER[0]) / 2,
                Y_BACK,
                -DRIVEN_RADIUS - 30) * Box(CENTER_DISTANCE + DRIVEN_RADIUS * 2,
                                            16,
                                            40,
                                            align=(Align.CENTER, Align.CENTER, Align.CENTER))
    post_driver = _cyl_along("Y", 14, 90,
                             center=(DRIVER_CENTER[0], Y_BACK - 30, DRIVER_CENTER[2]))
    post_driven = _cyl_along("Y", 14, 90,
                             center=(DRIVEN_CENTER[0], Y_BACK - 30, DRIVEN_CENTER[2]))
    return _compound_of([plate, post_driver, post_driven], label="base")


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def gen_step() -> Compound:
    children = [
        make_base_plate(),     # o1.1
        make_driver_disc(),    # o1.2
        make_lock_disc(),      # o1.3
        make_pin(),            # o1.4
        make_driven_wheel(),   # o1.5
    ]
    return Compound(label="geneva_drive", children=children)


if __name__ == "__main__":
    g = gen_step()
    print(f"children: {len(g.children)}")
    for i, c in enumerate(g.children, 1):
        print(f"  o1.{i}: {c.label}")
