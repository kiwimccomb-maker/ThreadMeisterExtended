"""Draw the insert-type button icons, isometric, in the add-in's flat palette.

Run from anywhere: python scripts/make_icons.py
Writes resources/icons/heatset/ and resources/icons/gripridge/ at 16/32/64/128.

The plate top faces are drawn flat in plan space and pushed through one affine
transform, which is exactly the isometric projection -- cheaper than laying out
every lobe by hand in screen coordinates.
"""
import math
import os

from PIL import Image, ImageDraw

S = 1024                      # render size, downsampled to the real icon sizes
PS = 1024                     # plan-space size for the top faces
SIZES = (128, 64, 32, 16)
K = math.cos(math.radians(30))

BLACK = (0, 0, 0, 255)
PLATE = (0, 190, 255, 255)    # same cyan as the existing add-in icon
PLATE_D = (0, 130, 190, 255)  # slab sides, one step down
WALL = (0, 96, 145, 255)      # the bore wall, in shadow
PLATE_M = (0, 165, 230, 255)  # ridge flanks inside the bore
BRASS = (255, 255, 0, 255)    # same yellow
BRASS_D = (205, 180, 0, 255)
VOID = (14, 26, 40, 255)      # the bottom of the hole
CLEAR = (0, 0, 0, 0)

LINE = 30                     # outline weight at S


def _circle(draw, cx, cy, r, **kw):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), **kw)


def _ellipse(draw, cx, cy, hw, hh, **kw):
    draw.ellipse((cx - hw, cy - hh, cx + hw, cy + hh), **kw)


def _iso(px, py, sc, cx, cy0):
    """Plan (px, py) -> screen, 30-degree isometric."""
    return cx + K * (px - py) * sc, cy0 + 0.5 * (px + py) * sc


def _to_iso(plan, sc, cx, cy0):
    """Project a whole plan-space layer. PIL wants the inverse map."""
    a = 1.0 / (2 * K * sc)
    b = 1.0 / sc
    return plan.transform(
        (S, S), Image.AFFINE,
        (a, b, -cx * a - cy0 * b, -a, b, cx * a - cy0 * b),
        resample=Image.BICUBIC)


def _slab(img, sc, cx, cy0, thickness):
    """The two visible side faces of the plate, plus their outlines."""
    d = ImageDraw.Draw(img)
    left = _iso(0, PS, sc, cx, cy0)
    front = _iso(PS, PS, sc, cx, cy0)
    right = _iso(PS, 0, sc, cx, cy0)
    for a, b in ((left, front), (front, right)):
        d.polygon([a, b, (b[0], b[1] + thickness), (a[0], a[1] + thickness)],
                  fill=PLATE_D, outline=BLACK, width=LINE)


SC = 0.56                     # shared plate scale, so both icons match
THICK = 110                   # plate thickness in screen pixels


def _plan_disc(r, fill):
    """Plan-space layer holding one filled circle at the plate centre."""
    layer = Image.new('RGBA', (PS, PS), CLEAR)
    _circle(ImageDraw.Draw(layer), PS / 2, PS / 2, r, fill=fill)
    return layer


def _plan_top():
    """Plan-space plate top face: flat fill with its outline."""
    top = Image.new('RGBA', (PS, PS), CLEAR)
    ImageDraw.Draw(top).rectangle(
        (0, 0, PS - 1, PS - 1), fill=PLATE, outline=BLACK, width=LINE)
    return top


def heatset():
    """A knurled brass insert standing in its bore in the plate."""
    cy0, cx = 202.0, S / 2
    img = Image.new('RGBA', (S, S), CLEAR)

    _slab(img, SC, cx, cy0, THICK)
    img.alpha_composite(_to_iso(_plan_top(), SC, cx, cy0))

    # Insert: a cylinder standing on the plate centre
    base_x, base_y = _iso(PS / 2, PS / 2, SC, cx, cy0)
    hw = 220.0                       # ellipse half-width
    hh = hw / math.sqrt(3)           # 30-degree isometric foreshortening
    height = 350.0
    top_y = base_y - height

    d = ImageDraw.Draw(img)
    _ellipse(d, base_x, base_y, hw, hh, fill=BRASS)
    d.rectangle((base_x - hw, top_y, base_x + hw, base_y), fill=BRASS)

    # Knurl: diagonal hatch, clipped to the barrel
    knurl = Image.new('RGBA', (S, S), CLEAR)
    kd = ImageDraw.Draw(knurl)
    for i in range(-2, 7):
        x = base_x - hw + i * (2 * hw / 6)
        kd.line((x, base_y + hh, x + height * 0.45, top_y), fill=BRASS_D,
                width=int(LINE * 1.5))
    barrel = Image.new('L', (S, S), 0)
    bd = ImageDraw.Draw(barrel)
    bd.rectangle((base_x - hw, top_y, base_x + hw, base_y), fill=255)
    _ellipse(bd, base_x, base_y, hw, hh, fill=255)
    img.paste(knurl, (0, 0),
              Image.composite(knurl.getchannel('A'), barrel, barrel))

    # Outlines last, so the knurl cannot eat into them
    d.arc((base_x - hw, base_y - hh, base_x + hw, base_y + hh), 0, 180,
          fill=BLACK, width=LINE)
    for x in (base_x - hw, base_x + hw):
        d.line((x, top_y, x, base_y), fill=BLACK, width=LINE)

    # Flange and the threaded bore down the middle
    _ellipse(d, base_x, top_y, hw, hh, fill=BRASS, outline=BLACK, width=LINE)
    _ellipse(d, base_x, top_y, hw * 0.52, hh * 0.52, fill=VOID, outline=BLACK,
             width=LINE)
    return img


# Proportions follow "M10 Grip" in config.ini (clearance 10.3, ridge dia 4.0,
# arc distance 6.45, count 6), with the ridges cut a little deeper so they still
# read at 16px. The arc centres sit outside the bore; only the sliver that falls
# inside it is material.
BORE = PS * 0.40              # clearance bore radius
RIDGE_R = PS * 0.115          # radius of each grip ridge arc
ARC = PS * 0.435              # arc centre distance from the bore axis
RIDGES = 6
DEPTH = 150                   # far enough that the lit wall is a crescent band
                              # with the dark floor under it, which is what reads
                              # as depth; deeper and the ridges become slabs


def _ridge_centres():
    return [(PS / 2 + ARC * math.cos(2 * math.pi * i / RIDGES),
             PS / 2 + ARC * math.sin(2 * math.pi * i / RIDGES))
            for i in range(RIDGES)]


def _iso_ellipse(r):
    """Screen half-width / half-height of a plan circle of radius r."""
    hw = math.sqrt(2) * K * r * SC
    return hw, hw / math.sqrt(3)


def _capsule(d, cx, cy, hw, hh, depth, fill):
    """A vertical cylinder seen from above: top ellipse plus barrel. It runs off
    the bottom of the bore, which is what makes the bore read as deep."""
    _ellipse(d, cx, cy, hw, hh, fill=fill)
    d.rectangle((cx - hw, cy, cx + hw, cy + depth), fill=fill)


def _ridge_faces(grow, fill):
    """Plan-space layer of the ridge slivers -- arc circles cut to the bore.
    `grow` fattens both radii, which is how the outline gets drawn: the fat
    black copy is swept first and the real one lands inside it."""
    layer = Image.new('RGBA', (PS, PS), CLEAR)
    ld = ImageDraw.Draw(layer)
    for lx, ly in _ridge_centres():
        _circle(ld, lx, ly, RIDGE_R + grow, fill=fill)
    bore = Image.new('L', (PS, PS), 0)
    _circle(ImageDraw.Draw(bore), PS / 2, PS / 2, BORE + grow, fill=255)
    layer.putalpha(Image.composite(layer.getchannel('A'), bore, bore))
    return layer


def _sweep(dst, layer, depth):
    """Extrude a projected layer straight down, far face first."""
    for dy in range(depth, -1, -3):
        dst.alpha_composite(layer, (0, dy))


def _opening_mask():
    """Plan-space mask of the bore's mouth: the bore less the ridge slivers."""
    mask = Image.new('L', (PS, PS), 0)
    md = ImageDraw.Draw(mask)
    _circle(md, PS / 2, PS / 2, BORE - LINE / 2, fill=255)
    for lx, ly in _ridge_centres():
        _circle(md, lx, ly, RIDGE_R + LINE / 2, fill=0)
    return mask


def gripridge():
    """A clearance bore with printed arc ridges a screw forms its thread against."""
    cy0, cx = 170.0, S / 2
    img = Image.new('RGBA', (S, S), CLEAR)
    _slab(img, SC, cx, cy0, THICK)

    bx, by = _iso(PS / 2, PS / 2, SC, cx, cy0)
    bw, bh = _iso_ellipse(BORE)

    # Drawn full, then cut to the mouth. Only the far wall survives the cut,
    # which is exactly what you see looking into a bore.
    inside = Image.new('RGBA', (S, S), CLEAR)
    d = ImageDraw.Draw(inside)
    _capsule(d, bx, by, bw, bh, DEPTH, WALL)
    _sweep(inside, _to_iso(_ridge_faces(LINE, BLACK), SC, cx, cy0), DEPTH)
    _sweep(inside, _to_iso(_ridge_faces(0, PLATE_M), SC, cx, cy0), DEPTH)
    # Floor last, so the ridges run down into it instead of floating
    _ellipse(d, bx, by + DEPTH, bw, bh, fill=VOID, outline=BLACK, width=LINE)

    mouth = _to_iso(Image.merge('RGBA', (_opening_mask(),) * 4), SC, cx, cy0)
    inside.putalpha(Image.composite(inside.getchannel('A'),
                                    Image.new('L', (S, S), 0),
                                    mouth.getchannel('A')))
    img.alpha_composite(inside)

    # Top face: plate, black bore rim, ridge crests, mouth punched through
    top = _plan_top()
    _circle(ImageDraw.Draw(top), PS / 2, PS / 2, BORE + LINE / 2, fill=BLACK)

    crests = Image.new('RGBA', (PS, PS), CLEAR)
    cd = ImageDraw.Draw(crests)
    for lx, ly in _ridge_centres():
        _circle(cd, lx, ly, RIDGE_R, fill=PLATE, outline=BLACK, width=LINE)
    rim = Image.new('L', (PS, PS), 0)
    _circle(ImageDraw.Draw(rim), PS / 2, PS / 2, BORE + LINE / 2, fill=255)
    top.paste(crests, (0, 0), Image.composite(crests.getchannel('A'), rim, rim))

    top.putalpha(Image.composite(Image.new('L', (PS, PS), 0),
                                 top.getchannel('A'), _opening_mask()))
    img.alpha_composite(_to_iso(top, SC, cx, cy0))
    return img


def main():
    root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    for name, build in (('heatset', heatset), ('gripridge', gripridge)):
        out = os.path.join(root, 'resources', 'icons', name)
        os.makedirs(out, exist_ok=True)
        art = build()
        for size in SIZES:
            art.resize((size, size), Image.LANCZOS).save(
                os.path.join(out, f'{size}x{size}.png'))
        print('wrote', out)


if __name__ == '__main__':
    main()
