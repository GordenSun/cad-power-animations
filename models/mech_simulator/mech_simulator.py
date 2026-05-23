"""Mechanism simulator — three classic mechanisms running side by side.

Units: millimeters. +X forward, +Y left, +Z up.

Layout, left → right along +X:
  - X ≈ -700: Crank-slider (rotary → linear)
  - X ≈    0: Cam follower (rotary → reciprocating with custom profile)
  - X ≈ +700: Gear pair (rotary → rotary at a fixed ratio)

All three are driven by a single `drive` angle. The sidecar exposes:
  - drive           (deg, animated)        — universal input angle
  - crank_radius    (mm, default 50)       — modifies the slider stroke;
                                            sidecar moves the visible pin
                                            and recomputes the rod tilt
  - cam_lift        (mm, default 22)       — extra lift the cam imparts
                                            to its follower (scales the
                                            profile rather than re-cutting
                                            geometry)
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
# Scene layout
# --------------------------------------------------------------------------- #
CS_X = -700.0        # crank-slider centre
CAM_X = 0.0          # cam centre
GR_X = +700.0        # gear pair centre
Y_PLANE = 0.0        # all rotors live in this Y plane (axes along +Y)

# --------------------------------------------------------------------------- #
# Crank-slider
# --------------------------------------------------------------------------- #
CS_DISC_R = 70.0
CS_DISC_T = 18.0
CS_PIN_R = 9.0
CS_PIN_L = 30.0
CS_PIN_OFFSET = 50.0    # default crank radius (sidecar can change effective via param)
CS_ROD_LEN = 220.0
CS_ROD_T = 16.0         # rod cross-section
CS_SLIDER_W = 70.0
CS_SLIDER_H = 40.0
CS_SLIDER_T = 40.0
CS_DISC_Z = 0.0
CS_GUIDE_LEN = 380.0
CS_GUIDE_T = 24.0

CS_SLIDER_X_ZERO = CS_X + CS_PIN_OFFSET + CS_ROD_LEN  # slider centre at θ=0
CS_GUIDE_CENTER_X = CS_SLIDER_X_ZERO - 70.0
CS_GUIDE_Z = CS_DISC_Z

# --------------------------------------------------------------------------- #
# Cam follower
# --------------------------------------------------------------------------- #
CAM_BASE_R = 50.0
CAM_LOBE_OFFSET = 22.0    # default lift (sidecar can scale follower travel)
CAM_T = 18.0
CAM_Z = 0.0
FOLLOWER_R = 14.0
FOLLOWER_LEN = 180.0
FOLLOWER_Z_ZERO = CAM_BASE_R + CAM_LOBE_OFFSET + FOLLOWER_LEN / 2
ROLLER_R = 16.0
FOLLOWER_GUIDE_R = 22.0
FOLLOWER_GUIDE_LEN = 120.0
FOLLOWER_GUIDE_Z = CAM_BASE_R + CAM_LOBE_OFFSET + 90.0

# --------------------------------------------------------------------------- #
# Gear pair
# --------------------------------------------------------------------------- #
GA_TEETH = 24
GB_TEETH = 12
GEAR_MOD = 6.0
GA_R = GA_TEETH * GEAR_MOD / 2     # 72 mm
GB_R = GB_TEETH * GEAR_MOD / 2     # 36 mm
GEAR_T = 20.0
GA_X = GR_X - GA_R - 4
GB_X = GA_X + GA_R + GB_R + 1.5     # tangent on the +X side
GEAR_Z = 0.0

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


def _toothed_disc(radius, teeth, thickness, center=(0, 0, 0)) -> Solid:
    """A gear-like disc: a cylinder with N small radial teeth around its rim.
    Not a real involute - just enough that the rotation reads visually."""
    body = _cyl_along("Y", radius, thickness, center=center)
    for i in range(teeth):
        ang = (i / teeth) * math.tau
        tooth_x = center[0] + (radius + 4) * math.cos(ang)
        tooth_z = center[2] + (radius + 4) * math.sin(ang)
        tooth = Box(8.0, thickness * 1.05, 10.0,
                    align=(Align.CENTER, Align.CENTER, Align.CENTER))
        tooth = Rot(0, math.degrees(-ang) + 90, 0) * tooth
        tooth = Pos(tooth_x, center[1], tooth_z) * tooth
        body = body + tooth
    # body might be a Compound after additions
    return body


# --------------------------------------------------------------------------- #
# Parts
# --------------------------------------------------------------------------- #


# ---- Crank-slider ----

def make_cs_crank() -> Compound:
    """Visible crank disc; axle along +Y so it spins around the world Y axis."""
    disc = _cyl_along("Y", CS_DISC_R, CS_DISC_T,
                      center=(CS_X, Y_PLANE, CS_DISC_Z))
    return _compound_of((disc,), label="cs_crank")


def make_cs_pin() -> Compound:
    """Crank pin sticking outboard (+Y) from the disc face, modeled at the
    'pin forward' position (θ=0). Sidecar moves it around the crank axis."""
    pin = _cyl_along("Y", CS_PIN_R, CS_PIN_L,
                     center=(CS_X + CS_PIN_OFFSET, Y_PLANE + CS_DISC_T / 2 + CS_PIN_L / 2,
                             CS_DISC_Z))
    return _compound_of((pin,), label="cs_pin")


def make_cs_rod() -> Compound:
    """Connecting rod modeled straight horizontally at θ=0."""
    big_x = CS_X + CS_PIN_OFFSET
    small_x = big_x + CS_ROD_LEN
    body = Pos((big_x + small_x) / 2, Y_PLANE + CS_DISC_T / 2 + CS_PIN_L / 2, CS_DISC_Z) * Box(
        CS_ROD_LEN, 10.0, CS_ROD_T,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    big = _cyl_along("Y", CS_ROD_T * 0.95, 16,
                     center=(big_x, Y_PLANE + CS_DISC_T / 2 + CS_PIN_L / 2, CS_DISC_Z))
    small = _cyl_along("Y", CS_ROD_T * 0.85, 14,
                       center=(small_x, Y_PLANE + CS_DISC_T / 2 + CS_PIN_L / 2, CS_DISC_Z))
    return _compound_of((body, big, small), label="cs_rod")


def make_cs_slider() -> Compound:
    body = Pos(CS_SLIDER_X_ZERO, Y_PLANE + CS_DISC_T / 2 + CS_PIN_L / 2, CS_DISC_Z) * Box(
        CS_SLIDER_W, 40, CS_SLIDER_H,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    return _compound_of((body,), label="cs_slider")


def make_cs_guide() -> Compound:
    """Static guide rail the slider rides on."""
    rail = Pos(CS_GUIDE_CENTER_X, Y_PLANE + CS_DISC_T / 2 + CS_PIN_L / 2,
               CS_DISC_Z - CS_SLIDER_H / 2 - 8) * Box(
        CS_GUIDE_LEN, 60, 12,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    return _compound_of((rail,), label="cs_guide")


# ---- Cam follower ----

def make_cam() -> Compound:
    """An offset disc + lobe so it visually 'kicks' the follower up once per
    revolution. Modeled as the base circle + a single bump on +X."""
    base = _cyl_along("Y", CAM_BASE_R, CAM_T,
                      center=(CAM_X, Y_PLANE, CAM_Z))
    lobe = Pos(CAM_X + CAM_BASE_R * 0.8, Y_PLANE, CAM_Z) * \
        Cylinder(CAM_BASE_R * 0.55, CAM_T,
                 align=(Align.CENTER, Align.CENTER, Align.CENTER))
    lobe = Rot(90, 0, 0) * lobe  # axis along Y
    lobe = Pos(0, Y_PLANE - 0, 0) * lobe  # no extra translate
    # Use the additive cylinder centred at the lobe position
    lobe2 = _cyl_along("Y", CAM_BASE_R * 0.55, CAM_T,
                       center=(CAM_X + CAM_BASE_R * 0.65, Y_PLANE, CAM_Z))
    return _compound_of((base, lobe2), label="cam")


def make_follower() -> Compound:
    """Vertical follower rod with a roller at the bottom. Modeled at its
    highest pose (cam lobe at top); sidecar translates it down + up as the
    cam rotates."""
    body = _cyl_along("Z", FOLLOWER_R, FOLLOWER_LEN,
                      center=(CAM_X, Y_PLANE, FOLLOWER_Z_ZERO))
    roller = _cyl_along("Y", ROLLER_R, 22,
                        center=(CAM_X, Y_PLANE, FOLLOWER_Z_ZERO - FOLLOWER_LEN / 2 - 4))
    cap = _cyl_along("Z", FOLLOWER_R + 6, 14,
                     center=(CAM_X, Y_PLANE, FOLLOWER_Z_ZERO + FOLLOWER_LEN / 2 + 7))
    return _compound_of((body, roller, cap), label="follower")


def make_follower_guide() -> Compound:
    """A short tube the follower passes through (so the audience reads the
    setup as 'sliding pair')."""
    outer = _cyl_along("Z", FOLLOWER_GUIDE_R, FOLLOWER_GUIDE_LEN,
                       center=(CAM_X, Y_PLANE, FOLLOWER_GUIDE_Z))
    inner = _cyl_along("Z", FOLLOWER_R + 2, FOLLOWER_GUIDE_LEN + 2,
                       center=(CAM_X, Y_PLANE, FOLLOWER_GUIDE_Z))
    return _compound_of((outer - inner,), label="follower_guide")


# ---- Gear pair ----

def make_gear_a() -> Compound:
    body = _toothed_disc(GA_R, GA_TEETH, GEAR_T,
                         center=(GA_X, Y_PLANE, GEAR_Z))
    # Pinion marker: a colored slot so rotation reads at a glance
    notch = Pos(GA_X + GA_R * 0.7, Y_PLANE, GEAR_Z) * Box(
        GA_R * 0.3, GEAR_T + 6, GA_R * 0.18,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    return _compound_of((body - notch,), label="gear_a")


def make_gear_b() -> Compound:
    body = _toothed_disc(GB_R, GB_TEETH, GEAR_T,
                         center=(GB_X, Y_PLANE, GEAR_Z))
    notch = Pos(GB_X + GB_R * 0.6, Y_PLANE, GEAR_Z) * Box(
        GB_R * 0.4, GEAR_T + 6, GB_R * 0.2,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    return _compound_of((body - notch,), label="gear_b")


# ---- Labels (small floating signs above each mechanism — purely decorative,
# but they make the demo readable at a glance) ----

def make_label_marker(x, color_label_text):
    """Returns a thin slab acting as a colour swatch above the mechanism."""
    body = Pos(x, Y_PLANE, 180) * Box(
        160, 6, 16,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    return body  # caller wraps in Compound


def make_legend() -> Compound:
    """Three coloured swatches (one above each mechanism) - the sidecar
    colours them so each mechanism has a matching label tint."""
    a = make_label_marker(CS_X, "crank")
    b = make_label_marker(CAM_X, "cam")
    c = make_label_marker(GR_X, "gear")
    return _compound_of((a, b, c), label="legend")


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def gen_step() -> Compound:
    children = [
        # Crank-slider (X ≈ -700)
        make_cs_guide(),     # o1.1
        make_cs_crank(),     # o1.2
        make_cs_pin(),       # o1.3
        make_cs_rod(),       # o1.4
        make_cs_slider(),    # o1.5
        # Cam follower (X ≈ 0)
        make_follower_guide(),  # o1.6
        make_cam(),          # o1.7
        make_follower(),     # o1.8
        # Gear pair (X ≈ +700)
        make_gear_a(),       # o1.9
        make_gear_b(),       # o1.10
        # Legend
        make_legend(),       # o1.11
    ]
    return Compound(label="mech_simulator", children=children)


if __name__ == "__main__":
    obj = gen_step()
    print(f"children: {len(obj.children)}")
    for i, c in enumerate(obj.children, start=1):
        print(f"  o1.{i}: {c.label}")
