"""F1 race car with a cut-away in-line four engine.

Units: millimeters.
Convention: +X forward (nose), +Y left, +Z up. Origin on ground plane,
mid-wheelbase center of the car.

The model is intentionally simplified - it is a teaching aid for the
"power principle" (combustion -> crankshaft rotation -> drive shaft ->
rear axle -> wheels). The exposed pistons, eccentric crank pins and the
drive train are all separate labeled children so the .f1_car.step.js
sidecar can animate them in the CAD Explorer viewer.

The order of children in the returned Compound matters: occurrence ids
(o1.1, o1.2 ...) follow that order. The sidecar references parts by
those ids; do not reorder without updating the sidecar.
"""

from __future__ import annotations

from build123d import (
    Align,
    Axis,
    Box,
    Cylinder,
    Compound,
    Location,
    Mode,
    Plane,
    Pos,
    Rot,
    Solid,
    Sphere,
    Vector,
)

# --------------------------------------------------------------------------- #
# parameters
# --------------------------------------------------------------------------- #

# Overall car envelope
WHEELBASE = 3600.0
TRACK = 1700.0
GROUND_CLEARANCE = 60.0

# Wheels / tyres
WHEEL_RADIUS = 360.0
WHEEL_WIDTH = 320.0
RIM_RADIUS = 200.0
RIM_THICKNESS = 60.0
HUB_RADIUS = 60.0
HUB_LENGTH = 60.0

# Axles
AXLE_RADIUS = 35.0
AXLE_LENGTH = TRACK - 2 * (WHEEL_WIDTH / 2 + 30.0)

# Chassis / monocoque
MONOCOQUE_LENGTH = 2800.0
MONOCOQUE_WIDTH = 700.0
MONOCOQUE_HEIGHT = 360.0
MONOCOQUE_Z = GROUND_CLEARANCE + 80.0

# Sidepods
SIDEPOD_LENGTH = 1700.0
SIDEPOD_WIDTH = 380.0
SIDEPOD_HEIGHT = 360.0
SIDEPOD_OFFSET_Y = MONOCOQUE_WIDTH / 2 + SIDEPOD_WIDTH / 2 - 30.0

# Nose
NOSE_LENGTH = 1100.0
NOSE_HEIGHT = 220.0
NOSE_TIP_WIDTH = 120.0

# Front wing
FRONT_WING_SPAN = 2000.0
FRONT_WING_CHORD = 380.0
FRONT_WING_THICK = 35.0
FRONT_WING_ENDPLATE_H = 220.0
FRONT_WING_ENDPLATE_T = 18.0

# Rear wing
REAR_WING_SPAN = 1100.0
REAR_WING_CHORD = 320.0
REAR_WING_THICK = 35.0
REAR_WING_HEIGHT = 950.0
REAR_WING_ENDPLATE_H = 320.0
REAR_WING_ENDPLATE_T = 22.0
REAR_WING_STRUT_T = 30.0

# Cockpit / halo
COCKPIT_OPEN_LENGTH = 700.0
COCKPIT_OPEN_WIDTH = 480.0
COCKPIT_OPEN_DEPTH = 240.0
HALO_TUBE_R = 18.0
HALO_ARC_R = 280.0
HALO_FRONT_R = 25.0

# Engine block (mid-rear, longitudinal)
ENGINE_CENTER_X = -1050.0
ENGINE_BLOCK_LENGTH = 900.0
ENGINE_BLOCK_WIDTH = 500.0
ENGINE_BLOCK_HEIGHT = 360.0
ENGINE_BLOCK_Z = 290.0  # absolute Z of engine block center

# Crankshaft kinematics (drives piston / rod geometry below).
# Place the crank axis inside the lower part of the engine block.
CRANK_AXIS_Z = ENGINE_BLOCK_Z - ENGINE_BLOCK_HEIGHT / 2 + 80.0  # 190
CRANK_R = 60.0     # half stroke
ROD_LENGTH = 260.0

# Cylinders / pistons
NUM_CYLINDERS = 4
CYL_SPACING = 180.0
CYL_BORE = 180.0  # piston OD
CYL_HEIGHT = 230.0  # visible bore sleeve height
CYL_WALL = 14.0
PISTON_HEIGHT = 90.0
# Static model places each piston at TDC. The connecting rod is modeled
# straight (vertical) at this pose, so:
#   PISTON_BOTTOM_Z(TDC) = CRANK_AXIS_Z + CRANK_R + ROD_LENGTH
PISTON_BOTTOM_Z = CRANK_AXIS_Z + CRANK_R + ROD_LENGTH
CRANK_MAIN_R = 22.0
CRANK_WEB_T = 28.0
CRANK_WEB_R = 70.0
CRANK_PIN_R = 22.0

DRIVE_SHAFT_R = 28.0
DRIVE_SHAFT_FRONT_X = ENGINE_CENTER_X + ENGINE_BLOCK_LENGTH / 2  # rear end of engine block
DRIVE_SHAFT_REAR_X = -WHEELBASE / 2 - 60.0  # rear axle x + a bit

DIFF_HOUSING_R = 140.0
DIFF_HOUSING_T = 200.0

# Cylinder bank x positions, centered on engine
_first = -((NUM_CYLINDERS - 1) / 2.0) * CYL_SPACING
CYL_X_POSITIONS = [ENGINE_CENTER_X + _first + i * CYL_SPACING for i in range(NUM_CYLINDERS)]

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _solid(*shapes) -> Solid:
    """Fuse shapes into a single Solid, robust to single-input case."""
    if len(shapes) == 1:
        s = shapes[0]
    else:
        s = shapes[0]
        for other in shapes[1:]:
            s = s + other
    if isinstance(s, Compound):
        # Promote first solid; build123d compounds usually wrap a single solid here.
        solids = s.solids()
        if len(solids) == 1:
            return solids[0]
        # Fall back to keeping compound but coerce label
        return s  # type: ignore[return-value]
    return s


def _box(length: float, width: float, height: float, center=(0, 0, 0)) -> Solid:
    return Pos(*center) * Box(length, width, height, align=(Align.CENTER, Align.CENTER, Align.CENTER))


def _cyl(radius: float, height: float, axis: str = "Z", center=(0, 0, 0)) -> Solid:
    base = Cylinder(radius, height, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    if axis.upper() == "X":
        base = Rot(0, 90, 0) * base
    elif axis.upper() == "Y":
        base = Rot(90, 0, 0) * base
    return Pos(*center) * base


def _tube(outer_r: float, inner_r: float, height: float, axis: str = "Z", center=(0, 0, 0)) -> Solid:
    outer = Cylinder(outer_r, height, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    inner = Cylinder(inner_r, height * 1.05, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    shell = outer - inner
    if axis.upper() == "X":
        shell = Rot(0, 90, 0) * shell
    elif axis.upper() == "Y":
        shell = Rot(90, 0, 0) * shell
    return Pos(*center) * shell


# --------------------------------------------------------------------------- #
# parts
# --------------------------------------------------------------------------- #


def make_monocoque() -> Solid:
    """Tapered survival cell, sits between the axles."""
    main = _box(MONOCOQUE_LENGTH, MONOCOQUE_WIDTH, MONOCOQUE_HEIGHT,
                center=(0, 0, MONOCOQUE_Z + MONOCOQUE_HEIGHT / 2))
    # subtract a cockpit opening on top, just forward of center
    cockpit = _box(
        COCKPIT_OPEN_LENGTH,
        COCKPIT_OPEN_WIDTH,
        COCKPIT_OPEN_DEPTH,
        center=(
            MONOCOQUE_LENGTH / 2 - COCKPIT_OPEN_LENGTH / 2 - 350.0,
            0,
            MONOCOQUE_Z + MONOCOQUE_HEIGHT - COCKPIT_OPEN_DEPTH / 2 + 1.0,
        ),
    )
    body = main - cockpit
    body.label = "monocoque"
    return body


def make_floor() -> Solid:
    body = _box(WHEELBASE + 600, TRACK - 100, 40,
                center=(-100.0, 0, GROUND_CLEARANCE + 20))
    body.label = "floor"
    return body


def make_left_sidepod() -> Solid:
    body = _box(SIDEPOD_LENGTH, SIDEPOD_WIDTH, SIDEPOD_HEIGHT,
                center=(-200.0, SIDEPOD_OFFSET_Y, MONOCOQUE_Z + SIDEPOD_HEIGHT / 2))
    body.label = "sidepod_left"
    return body


def make_right_sidepod() -> Solid:
    body = _box(SIDEPOD_LENGTH, SIDEPOD_WIDTH, SIDEPOD_HEIGHT,
                center=(-200.0, -SIDEPOD_OFFSET_Y, MONOCOQUE_Z + SIDEPOD_HEIGHT / 2))
    body.label = "sidepod_right"
    return body


def make_nose() -> Solid:
    nose_back = _box(60, MONOCOQUE_WIDTH, NOSE_HEIGHT,
                     center=(MONOCOQUE_LENGTH / 2 + 30, 0,
                             MONOCOQUE_Z + NOSE_HEIGHT / 2))
    # Long tapered nose using lofted approach via simple boxes
    nose_mid = _box(NOSE_LENGTH * 0.6, MONOCOQUE_WIDTH * 0.7, NOSE_HEIGHT * 0.85,
                    center=(MONOCOQUE_LENGTH / 2 + 60 + NOSE_LENGTH * 0.3, 0,
                            MONOCOQUE_Z + NOSE_HEIGHT * 0.85 / 2 + 10))
    nose_tip = _box(NOSE_LENGTH * 0.4, NOSE_TIP_WIDTH, NOSE_HEIGHT * 0.7,
                    center=(MONOCOQUE_LENGTH / 2 + 60 + NOSE_LENGTH * 0.8,
                            0, MONOCOQUE_Z + NOSE_HEIGHT * 0.7 / 2 + 20))
    body = nose_back + nose_mid + nose_tip
    body.label = "nose"
    return body


def make_front_wing() -> Solid:
    wing_x = MONOCOQUE_LENGTH / 2 + NOSE_LENGTH + 60
    plane = _box(FRONT_WING_CHORD, FRONT_WING_SPAN, FRONT_WING_THICK,
                 center=(wing_x, 0, GROUND_CLEARANCE + 90))
    ep_left = _box(FRONT_WING_CHORD * 1.1, FRONT_WING_ENDPLATE_T, FRONT_WING_ENDPLATE_H,
                   center=(wing_x, FRONT_WING_SPAN / 2,
                           GROUND_CLEARANCE + 90 + FRONT_WING_ENDPLATE_H / 2 - FRONT_WING_THICK / 2))
    ep_right = _box(FRONT_WING_CHORD * 1.1, FRONT_WING_ENDPLATE_T, FRONT_WING_ENDPLATE_H,
                    center=(wing_x, -FRONT_WING_SPAN / 2,
                            GROUND_CLEARANCE + 90 + FRONT_WING_ENDPLATE_H / 2 - FRONT_WING_THICK / 2))
    body = plane + ep_left + ep_right
    body.label = "front_wing"
    return body


def make_rear_wing() -> Solid:
    wing_x = -MONOCOQUE_LENGTH / 2 - 250
    plane = _box(REAR_WING_CHORD, REAR_WING_SPAN, REAR_WING_THICK,
                 center=(wing_x, 0, REAR_WING_HEIGHT))
    ep_left = _box(REAR_WING_CHORD * 1.1, REAR_WING_ENDPLATE_T, REAR_WING_ENDPLATE_H,
                   center=(wing_x, REAR_WING_SPAN / 2,
                           REAR_WING_HEIGHT))
    ep_right = _box(REAR_WING_CHORD * 1.1, REAR_WING_ENDPLATE_T, REAR_WING_ENDPLATE_H,
                    center=(wing_x, -REAR_WING_SPAN / 2,
                            REAR_WING_HEIGHT))
    strut = _box(60, REAR_WING_STRUT_T, REAR_WING_HEIGHT - MONOCOQUE_Z,
                 center=(wing_x, 0, MONOCOQUE_Z + (REAR_WING_HEIGHT - MONOCOQUE_Z) / 2))
    body = plane + ep_left + ep_right + strut
    body.label = "rear_wing"
    return body


def make_halo() -> Solid:
    # Front hoop in front of cockpit opening
    front_x = MONOCOQUE_LENGTH / 2 - 350.0 - COCKPIT_OPEN_LENGTH / 2 + 60
    halo_top_z = MONOCOQUE_Z + MONOCOQUE_HEIGHT + 280.0
    front_pillar = _cyl(HALO_FRONT_R, halo_top_z - (MONOCOQUE_Z + MONOCOQUE_HEIGHT),
                        axis="Z",
                        center=(front_x, 0,
                                MONOCOQUE_Z + MONOCOQUE_HEIGHT +
                                (halo_top_z - (MONOCOQUE_Z + MONOCOQUE_HEIGHT)) / 2))
    arc_back_x = front_x - 950.0
    # crude halo arc: two long tubes from front pillar going back along Y= ± half-width to roll hoop
    left_arc = _box(950, HALO_TUBE_R * 2, HALO_TUBE_R * 2,
                    center=((front_x + arc_back_x) / 2,
                            COCKPIT_OPEN_WIDTH / 2 + 30, halo_top_z))
    right_arc = _box(950, HALO_TUBE_R * 2, HALO_TUBE_R * 2,
                     center=((front_x + arc_back_x) / 2,
                             -(COCKPIT_OPEN_WIDTH / 2 + 30), halo_top_z))
    roll_hoop = _box(80, COCKPIT_OPEN_WIDTH + 80, halo_top_z - MONOCOQUE_Z + 40,
                     center=(arc_back_x, 0,
                             MONOCOQUE_Z + (halo_top_z - MONOCOQUE_Z + 40) / 2))
    body = front_pillar + left_arc + right_arc + roll_hoop
    body.label = "halo"
    return body


def make_engine_block() -> Solid:
    block = _box(ENGINE_BLOCK_LENGTH, ENGINE_BLOCK_WIDTH, ENGINE_BLOCK_HEIGHT,
                 center=(ENGINE_CENTER_X, 0, ENGINE_BLOCK_Z))
    # Drill the four piston bores out of the top so pistons can travel into
    # the block. Bore reaches down past the BDC bottom of the piston so the
    # piston bottom (PISTON_BOTTOM_Z - 2 * CRANK_R) clears.
    bore_top_z = ENGINE_BLOCK_Z + ENGINE_BLOCK_HEIGHT / 2
    piston_bdc = PISTON_BOTTOM_Z - 2 * CRANK_R
    bore_bottom_z = piston_bdc - 30
    bore_depth = bore_top_z - bore_bottom_z + 4
    for x in CYL_X_POSITIONS:
        bore = _cyl(CYL_BORE / 2 + 4, bore_depth, axis="Z",
                    center=(x, 0, bore_top_z - bore_depth / 2 + 2))
        block = block - bore
    block.label = "engine_block"
    return block


def make_cylinder_sleeve(index: int) -> Solid:
    """A thin half-pipe around each piston bore so the piston motion is
    framed without being hidden. The +Y half is cut open as a viewing window
    so the audience can see the piston traveling inside."""
    x = CYL_X_POSITIONS[index]
    sleeve_bottom = ENGINE_BLOCK_Z + ENGINE_BLOCK_HEIGHT / 2 - 10.0
    sleeve_height = CYL_HEIGHT
    sleeve_center_z = sleeve_bottom + sleeve_height / 2
    sleeve = _tube(CYL_BORE / 2 + CYL_WALL, CYL_BORE / 2 + 1,
                   sleeve_height, axis="Z",
                   center=(x, 0, sleeve_center_z))
    window = _box(CYL_BORE + 2 * CYL_WALL + 4,
                  CYL_BORE / 2 + CYL_WALL + 5,
                  sleeve_height + 4,
                  center=(x, (CYL_BORE / 2 + CYL_WALL + 5) / 2, sleeve_center_z))
    sleeve = sleeve - window
    sleeve.label = f"cylinder_sleeve_{index + 1}"
    return sleeve


def make_piston(index: int) -> Solid:
    """A piston modeled at TDC. The sidecar translates it on -Z each frame."""
    x = CYL_X_POSITIONS[index]
    body = _cyl(CYL_BORE / 2 - 4, PISTON_HEIGHT, axis="Z",
                center=(x, 0, PISTON_BOTTOM_Z + PISTON_HEIGHT / 2))
    # small pin lug
    lug = _box(40, CYL_BORE / 2 + 30, 30,
               center=(x, 0, PISTON_BOTTOM_Z + 30))
    body = body + lug
    body.label = f"piston_{index + 1}"
    return body


def make_connecting_rod(index: int) -> Solid:
    """Modeled straight at TDC, sliding down the rod axis as crank turns.
    The sidecar tilts and translates it to follow the crank pin orbit."""
    x = CYL_X_POSITIONS[index]
    rod_thickness = 28.0
    rod_width = 60.0
    # Centered so its top is at PISTON_BOTTOM_Z and bottom is at PISTON_BOTTOM_Z - ROD_LENGTH
    rod = _box(rod_thickness, rod_width, ROD_LENGTH,
               center=(x, 0, PISTON_BOTTOM_Z - ROD_LENGTH / 2))
    small_end = _cyl(30, rod_thickness * 1.3, axis="X",
                     center=(x, 0, PISTON_BOTTOM_Z))
    big_end = _cyl(45, rod_thickness * 1.4, axis="X",
                   center=(x, 0, PISTON_BOTTOM_Z - ROD_LENGTH))
    body = rod + small_end + big_end
    body.label = f"con_rod_{index + 1}"
    return body


def make_crankshaft() -> Solid:
    """One rigid body: main journal along X plus 4 throws.

    Modeled with phases (0, 180, 180, 0) so a single rotation around the
    X-axis (Y=0, Z=CRANK_AXIS_Z) animates the eccentric pin orbits.

    NOTE: the crank pins are placed at angle 0 (top dead center) for
    cylinders 1 & 4 and 180 (bottom dead center) for cylinders 2 & 3.
    """
    # Main journal: cylinder along X
    span = max(CYL_X_POSITIONS) - min(CYL_X_POSITIONS) + 200
    main = _cyl(CRANK_MAIN_R, span, axis="X",
                center=((max(CYL_X_POSITIONS) + min(CYL_X_POSITIONS)) / 2,
                        0, CRANK_AXIS_Z))
    crank = main
    phases_deg = [0, 180, 180, 0]
    for x, phase in zip(CYL_X_POSITIONS, phases_deg):
        # Web: thin disk facing along X
        web = _cyl(CRANK_WEB_R, CRANK_WEB_T, axis="X",
                   center=(x - 25, 0, CRANK_AXIS_Z))
        web2 = _cyl(CRANK_WEB_R, CRANK_WEB_T, axis="X",
                    center=(x + 25, 0, CRANK_AXIS_Z))
        # Pin: short cylinder along X, offset by CRANK_R in YZ at the given phase
        from math import radians, sin, cos
        py = CRANK_R * sin(radians(phase))
        pz = CRANK_AXIS_Z + CRANK_R * cos(radians(phase))
        pin = _cyl(CRANK_PIN_R, 60.0, axis="X", center=(x, py, pz))
        crank = crank + web + web2 + pin
    crank.label = "crankshaft"
    return crank


def make_clutch_bell() -> Solid:
    body = _cyl(110, 70, axis="X",
                center=(DRIVE_SHAFT_FRONT_X + 50, 0, CRANK_AXIS_Z))
    body.label = "clutch_bell"
    return body


def make_drive_shaft() -> Solid:
    length = DRIVE_SHAFT_FRONT_X + 80 - DRIVE_SHAFT_REAR_X
    body = _cyl(DRIVE_SHAFT_R, length, axis="X",
                center=((DRIVE_SHAFT_FRONT_X + 80 + DRIVE_SHAFT_REAR_X) / 2,
                        0, CRANK_AXIS_Z))
    body.label = "drive_shaft"
    return body


def make_differential() -> Solid:
    """Diff housing sits between drive shaft and rear axle."""
    body = _cyl(DIFF_HOUSING_R, DIFF_HOUSING_T, axis="Y",
                center=(DRIVE_SHAFT_REAR_X, 0, CRANK_AXIS_Z))
    # crown gear marker on the front
    crown = _cyl(DIFF_HOUSING_R * 0.95, 24, axis="X",
                 center=(DRIVE_SHAFT_REAR_X + 30, 0, CRANK_AXIS_Z))
    body = body + crown
    body.label = "differential"
    return body


def make_axle(rear: bool) -> Solid:
    x = -WHEELBASE / 2 if rear else WHEELBASE / 2
    body = _cyl(AXLE_RADIUS, AXLE_LENGTH, axis="Y", center=(x, 0, WHEEL_RADIUS))
    body.label = "rear_axle" if rear else "front_axle"
    return body


def make_wheel(side_y: float, x: float, label: str) -> Solid:
    """Tyre + rim modeled as one solid. Rotates around its own Y-axis."""
    tyre = _tube(WHEEL_RADIUS, RIM_RADIUS, WHEEL_WIDTH, axis="Y",
                 center=(x, side_y, WHEEL_RADIUS))
    rim_disc = _cyl(RIM_RADIUS, RIM_THICKNESS, axis="Y",
                    center=(x, side_y + (WHEEL_WIDTH / 2 - RIM_THICKNESS / 2 - 20),
                            WHEEL_RADIUS))
    # 5 cosmetic spoke holes on the outboard face (optional, light visual).
    hub = _cyl(HUB_RADIUS, HUB_LENGTH, axis="Y",
               center=(x, side_y + WHEEL_WIDTH / 2 - HUB_LENGTH / 2, WHEEL_RADIUS))
    body = tyre + rim_disc + hub
    body.label = label
    return body


def make_driver_helmet() -> Solid:
    cockpit_x = MONOCOQUE_LENGTH / 2 - 350.0 - COCKPIT_OPEN_LENGTH / 2 + 50
    head = Sphere(140) + Pos(0, 0, -90) * Cylinder(140, 200, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    head = Pos(cockpit_x, 0, MONOCOQUE_Z + MONOCOQUE_HEIGHT + 140) * head
    head.label = "driver_helmet"
    return head


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #


def gen_step() -> Compound:
    """Build the labeled assembly. Child order = occurrence id order."""
    children = []

    # Body / aero
    children.append(make_monocoque())              # o1.1
    children.append(make_floor())                  # o1.2
    children.append(make_left_sidepod())           # o1.3
    children.append(make_right_sidepod())          # o1.4
    children.append(make_nose())                   # o1.5
    children.append(make_front_wing())             # o1.6
    children.append(make_rear_wing())              # o1.7
    children.append(make_halo())                   # o1.8
    children.append(make_driver_helmet())          # o1.9

    # Engine internals (visible cut-away)
    children.append(make_engine_block())           # o1.10
    for i in range(NUM_CYLINDERS):
        children.append(make_cylinder_sleeve(i))   # o1.11..o1.14
    for i in range(NUM_CYLINDERS):
        children.append(make_piston(i))            # o1.15..o1.18
    for i in range(NUM_CYLINDERS):
        children.append(make_connecting_rod(i))    # o1.19..o1.22
    children.append(make_crankshaft())             # o1.23
    children.append(make_clutch_bell())            # o1.24
    children.append(make_drive_shaft())            # o1.25
    children.append(make_differential())           # o1.26

    # Suspension / wheels
    children.append(make_axle(rear=False))         # o1.27
    children.append(make_axle(rear=True))          # o1.28
    children.append(make_wheel(+TRACK / 2, +WHEELBASE / 2, "wheel_fl"))   # o1.29
    children.append(make_wheel(-TRACK / 2, +WHEELBASE / 2, "wheel_fr"))   # o1.30
    children.append(make_wheel(+TRACK / 2, -WHEELBASE / 2, "wheel_rl"))   # o1.31
    children.append(make_wheel(-TRACK / 2, -WHEELBASE / 2, "wheel_rr"))   # o1.32

    car = Compound(label="f1_car", children=children)
    return car


if __name__ == "__main__":
    car = gen_step()
    print(f"children: {len(car.children)}")
    for i, c in enumerate(car.children, start=1):
        print(f"  o1.{i}: {c.label}")
