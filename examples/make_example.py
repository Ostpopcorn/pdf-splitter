"""Make examples/example.pdf: notes like from a reMarkable, with a page that
is much longer than A4 and a page that fits, written in a script font whose
glyphs are drawn as paths, like the strokes of a reMarkable.

    pip install fonttools brotli
    python examples/make_example.py
"""
import os
import random

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from pypdf import PdfWriter
from pypdf.generic import (DecodedStreamObject, DictionaryObject, NameObject,
                           RectangleObject)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = os.path.join(ROOT, "web", "fonts", "parisienne.woff2")
OUT = os.path.join(ROOT, "examples", "example.pdf")

font = TTFont(FONT)
cmap = font.getBestCmap()
glyphs = font.getGlyphSet()
hmtx = font["hmtx"]
UPEM = font["head"].unitsPerEm


class PdfPen(BasePen):
    def __init__(self, glyphset):
        super().__init__(glyphset)
        self.ops = []

    def p(self, pt):
        return "{:g} {:g}".format(round(pt[0]), round(pt[1]))

    def _moveTo(self, pt):
        self.ops.append(self.p(pt) + " m")

    def _lineTo(self, pt):
        self.ops.append(self.p(pt) + " l")

    def _curveToOne(self, p1, p2, p3):
        self.ops.append(" ".join([self.p(p1), self.p(p2), self.p(p3)]) + " c")

    def _qCurveToOne(self, p1, p2):
        p0 = self._getCurrentPoint()
        c1 = (p0[0] + 2 / 3 * (p1[0] - p0[0]), p0[1] + 2 / 3 * (p1[1] - p0[1]))
        c2 = (p2[0] + 2 / 3 * (p1[0] - p2[0]), p2[1] + 2 / 3 * (p1[1] - p2[1]))
        self._curveToOne(c1, c2, p2)

    def _closePath(self):
        self.ops.append("h")


USED = {}


def glyph_form(name):
    """The name of the form XObject of a glyph in font units."""
    if name not in USED:
        pen = PdfPen(glyphs)
        glyphs[name].draw(pen)
        USED[name] = ("/G{}".format(len(USED)), "\n".join(pen.ops + ["f"]))
    return USED[name][0]


def text(string, x, y, size):
    """Operators that draw the text with its baseline at y (from the
    bottom), and the width of the text."""
    scale = size / UPEM
    ops = []
    pen_x = x
    rnd = random.Random(string)
    for char in string:
        if char == " ":
            pen_x += size * 0.28
            continue
        name = cmap.get(ord(char))
        if name is None:
            continue
        # a hand does not write on a ruler
        dy = rnd.uniform(-0.6, 0.6)
        ops.append("q {:.5f} 0 0 {:.5f} {:.2f} {:.2f} cm {} Do Q".format(
            scale, scale, pen_x, y + dy, glyph_form(name)))
        pen_x += hmtx[name][0] * scale
    return ops, pen_x - x


def wobbly(points, rnd, jitter=0.8):
    ops = []
    for i, (x, y) in enumerate(points):
        x += rnd.uniform(-jitter, jitter)
        y += rnd.uniform(-jitter, jitter)
        ops.append("{:.2f} {:.2f} {}".format(x, y, "m" if i == 0 else "l"))
    return ops


def page(width, height, lines, sketch=None, highlight=()):
    rnd = random.Random(len(lines))
    ops = []
    # the lined template of the reMarkable
    ops.append("0.82 0.82 0.82 RG 0.5 w")
    spacing = 31
    top = height - 78
    y = top
    while y > 30:
        ops.append("28 {0:.2f} m {1:.2f} {0:.2f} l S".format(y, width - 28))
        y -= spacing
    # the highlighted words, behind the writing
    for row, start, end in highlight:
        y = top - row * spacing
        ops.append("1 0.93 0.35 rg {:.2f} {:.2f} {:.2f} {:.2f} re f".format(
            start, y - 4, end - start, 20))
    ops.append("0.12 0.12 0.14 rg")
    for row, (string, size, indent) in enumerate(lines):
        if not string:
            continue
        y = top - row * spacing + 3
        glyph_ops, _ = text(string, 44 + indent, y, size)
        ops += glyph_ops
    if sketch:
        ops.append(sketch(rnd))
    return "\n".join(ops).encode()


def sketch(top):
    """A hand drawn sketch of a long page split onto three pages, which
    overlap, at the row top."""
    def draw(rnd):
        ops = ["0.12 0.12 0.14 RG 1.6 w 1 J 1 j"]
        y0 = top
        # the long page
        x, w, h = 70, 70, 175
        ops += wobbly([(x, y0), (x + w, y0), (x + w, y0 - h), (x, y0 - h), (x, y0)], rnd)
        ops.append("S")
        # the pages of paper, which overlap
        for i in range(3):
            px = 190 + i * 70
            ops += wobbly([(px, y0), (px + 58, y0), (px + 58, y0 - 72), (px, y0 - 72), (px, y0)], rnd)
            ops.append("S")
        # the overlap, marked on the long page
        ops.append("0.86 0.36 0.1 RG 1.2 w")
        for y in (y0 - 62, y0 - 72, y0 - 113, y0 - 123):
            ops += wobbly([(x - 6, y), (x + w + 6, y)], rnd, 0.5)
            ops.append("S")
        ops.append("0.12 0.12 0.14 RG 1.6 w")
        # an arrow
        ops += wobbly([(150, y0 - 90), (180, y0 - 90)], rnd, 0.3)
        ops += wobbly([(172, y0 - 84), (181, y0 - 90), (172, y0 - 96)], rnd, 0.3)
        ops.append("S")
        return "\n".join(ops)
    return draw


W = 447
LONG = 1660
long_lines = [
    ("Printing my notes", 30, 0),
    ("", 0, 0),
    ("I kept writing, and the page kept", 22, 0),
    ("growing. Now it is much longer", 22, 0),
    ("than a page of A4 paper.", 22, 0),
    ("", 0, 0),
    ("Scaled down to one page, the", 22, 0),
    ("writing is tiny. Split onto pages,", 22, 0),
    ("some lines are cut in half, with", 22, 0),
    ("their top on one page and their", 22, 0),
    ("bottom on the next one.", 22, 0),
    ("", 0, 0),
    ("The fix: an overlap. The end of", 22, 0),
    ("each page is repeated at the top", 22, 0),
    ("of the next one, so that a line", 22, 0),
    ("that is cut is whole on the next", 22, 0),
    ("page.", 22, 0),
    ("", 0, 0),
    ("Here is how it looks on paper:", 22, 0),
    ("", 0, 0),
    ("", 0, 0),
    ("", 0, 0),
    ("", 0, 0),
    ("", 0, 0),
    ("", 0, 0),
    ("", 0, 0),
    ("", 0, 0),
    ("To do:", 24, 0),
    ("- an overlap of about two lines", 22, 10),
    ("- a margin if the printer cuts", 22, 10),
    ("   the edges of the paper", 22, 10),
    ("- print it all on A4", 22, 10),
    ("", 0, 0),
    ("", 0, 0),
    ("Each page is scaled to the width", 22, 0),
    ("of the paper, so the writing", 22, 0),
    ("stays as large as on the tablet,", 22, 0),
    ("and the strokes stay sharp.", 22, 0),
    ("", 0, 0),
    ("A page that fits stays one page,", 22, 0),
    ("like the next one.", 22, 0),
    ("", 0, 0),
    ("Done!", 26, 150),
    ("", 0, 0),
    ("P.S. Point at a page on the right", 22, 0),
    ("to see where it comes from, and", 22, 0),
    ("click it to scroll there.", 22, 0),
]
short_lines = [
    ("A short page", 30, 0),
    ("", 0, 0),
    ("This page is as high as the", 22, 0),
    ("screen of the tablet, and fits", 22, 0),
    ("on one page of A4.", 22, 0),
    ("", 0, 0),
    ("Pages like this one are scaled to", 22, 0),
    ("the width of the paper, like the", 22, 0),
    ("long page, so that all the pages", 22, 0),
    ("have the same size of writing.", 22, 0),
]
long_top = LONG - 78
writer = PdfWriter()
pages = [(W, LONG, page(W, LONG, long_lines, sketch(long_top - 19 * 31 + 12),
                        highlight=[(12, 44, 330)])),
         (W, 596, page(W, 596, short_lines))]
forms = DictionaryObject()
for name, (key, ops) in USED.items():
    form = DecodedStreamObject()
    form.set_data(ops.encode())
    form.update({NameObject("/Type"): NameObject("/XObject"),
                 NameObject("/Subtype"): NameObject("/Form"),
                 NameObject("/BBox"): RectangleObject((-2000, -2000, 4000, 4000))})
    forms[NameObject(key)] = writer._add_object(form.flate_encode())
resources = writer._add_object(DictionaryObject({NameObject("/XObject"): forms}))
for width, height, content in pages:
    p = writer.add_blank_page(width, height)
    p[NameObject("/Resources")] = resources
    stream = DecodedStreamObject()
    stream.set_data(content)
    p.replace_contents(stream.flate_encode())
writer.add_metadata({"/Title": "Printing my notes"})
writer.compress_identical_objects()
with open(OUT, "wb") as f:
    writer.write(f)
