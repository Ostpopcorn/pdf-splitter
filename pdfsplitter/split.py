"""Split tall pages onto pages of paper with an overlap.

Notes exported from a reMarkable can have pages that are longer than a page
of paper. Each page is scaled to the width of the paper, within its margins,
and cut into slices as high as the paper. The slices overlap: the end of
each slice is repeated at the top of the next one, so that a line of
handwriting that is cut at the end of a page is whole on the next page.

The page is copied once into the new PDF as a form XObject, which each slice
shows, so that the strokes stay vectors and the file does not grow with the
number of slices.
"""
import io
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (DecodedStreamObject, DictionaryObject, NameObject,
                           RectangleObject)

MM = 72 / 25.4  # points per mm

# Width and height of the papers in mm
PAPERS = {
    "a3": (297, 420),
    "a4": (210, 297),
    "a5": (148, 210),
    "letter": (215.9, 279.4),
    "legal": (215.9, 355.6),
}

# A page that is at most this much higher than a slice, in points on the
# paper, is not split, so that rounding never adds an empty page
_TOLERANCE = 0.01


@dataclass(frozen=True)
class Options:
    """How to split the pages.

    The overlap and the margin are in mm on the paper. The overlap is the end
    of a page that is repeated at the top of the next one. It can be at most
    half of the height of the paper within the margins. A page is made up to
    shrink percent smaller than the width of the paper, if it then needs
    fewer pages, e.g., a page that is a bit too long for one page."""
    paper: str = "a4"
    overlap: float = 20
    margin: float = 0
    shrink: float = 10


@dataclass(frozen=True)
class Layout:
    """The slices of a page, each on a page of paper. The width and the height
    of the page are in points, as it is shown, i.e., rotated by /Rotate. The
    top and bottom of each slice are in points from the top of the page. The
    last slice may end below the page, where the paper stays empty. A page
    that is shrunk is centered, left is the space on its left within the
    margins in points on the paper."""
    width: float
    height: float
    scale: float
    slices: List[Tuple[float, float]] = field(default_factory=list)
    left: float = 0


@dataclass(frozen=True)
class Result:
    """The new PDF and the layout of each page of the original."""
    data: bytes
    layouts: List[Layout]

    @property
    def pages(self):
        return sum(len(_layout.slices) for _layout in self.layouts)


def paper_size(options):
    """Return the width and the height of the paper in points."""
    try:
        width, height = PAPERS[options.paper.lower()]
    except KeyError:
        raise ValueError("Unknown paper {!r}, choose one of {}".format(
            options.paper, ", ".join(PAPERS))) from None
    return width * MM, height * MM


def max_overlap(options):
    """Return the largest overlap in mm for the paper and the margin."""
    _, height = paper_size(options)
    return max(0.0, (height / MM - 2 * options.margin) / 2)


def _content_size(options):
    """The width and the height of the paper within the margins, in points,
    and the overlap in points."""
    width, height = paper_size(options)
    margin = options.margin * MM
    if options.margin < 0 or 2 * margin >= min(width, height):
        raise ValueError("The margin must be between 0 and {:g} mm".format(
            math.floor(min(width, height) / MM / 2)))
    if not 0 <= options.overlap <= max_overlap(options):
        raise ValueError(
            "The overlap must be between 0 and {:g} mm, half of the paper "
            "within the margins".format(math.floor(max_overlap(options))))
    if not 0 <= options.shrink <= 50:
        raise ValueError("The shrink must be between 0 and 50 %")
    return width - 2 * margin, height - 2 * margin, options.overlap * MM


def layout_page(width, height, options=Options()):
    """Return the layout of a page of the width and the height in points."""
    if width <= 0 or height <= 0:
        raise ValueError("The page has no area")
    # in points on the paper
    content_width, content_height, overlap = _content_size(options)
    step = content_height - overlap
    scale = content_width / width
    rest = height * scale - content_height
    count = 1 if rest <= _TOLERANCE else 1 + math.ceil(
        (rest - _TOLERANCE) / step)
    # a smaller page on fewer pages of paper, as long as it is not smaller
    # than the shrink allows
    smallest = scale * (1 - options.shrink / 100) * (1 - 1e-9)
    while count > 1:
        fit = ((count - 1) * step + overlap) / height
        if fit < smallest:
            break
        scale, count = fit, count - 1
    size = content_height / scale
    return Layout(width, height, scale,
                  [(_i * step / scale, _i * step / scale + size)
                   for _i in range(count)],
                  (content_width - width * scale) / 2)


def _page_box(page):
    """The box of a page that is shown, (x0, y0, x1, y1), and its rotation."""
    crop = page.cropbox
    media = page.mediabox
    # the crop box is the part of the media box that is shown
    box = (max(float(crop.left), float(media.left)),
           max(float(crop.bottom), float(media.bottom)),
           min(float(crop.right), float(media.right)),
           min(float(crop.top), float(media.top)))
    if box[2] <= box[0] or box[3] <= box[1]:
        box = tuple(float(_value) for _value in media)
    rotation = int(page.rotation) % 360
    if rotation % 90:
        rotation = 0
    return box, rotation


def _shown_size(box, rotation):
    """The width and the height of a page as it is shown."""
    size = (box[2] - box[0], box[3] - box[1])
    return size[::-1] if rotation in (90, 270) else size


def page_sizes(reader):
    """Return the width and the height of each page as it is shown."""
    return [_shown_size(*_page_box(_page)) for _page in reader.pages]


def count_annotations(reader):
    """Return the number of annotations that are shown on the pages, e.g.,
    comments, which are not in the split PDF. Links are not shown."""
    count = 0
    for _page in reader.pages:
        for _annotation in _page.get("/Annots") or []:
            annotation = _annotation.get_object()
            # the flag 2 hides an annotation
            if "/AP" in annotation and not int(annotation.get("/F", 0)) & 2:
                count += 1
    return count


def _rotation_matrix(box, rotation):
    """The matrix from the space of the page to the page as it is shown,
    with its lower left corner at 0, 0. /Rotate turns it clockwise."""
    x0, y0, x1, y1 = box
    return {0: (1, 0, 0, 1, -x0, -y0),
            90: (0, -1, 1, 0, -y0, x1),
            180: (-1, 0, 0, -1, x1, y1),
            270: (0, 1, -1, 0, y1, -x0)}[rotation]


def _number(value):
    text = "{:.4f}".format(value).rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _form_xobject(writer, page, box):
    """Add the page to the writer as a form XObject and return it."""
    contents = page.get_contents()
    form = DecodedStreamObject()
    form.set_data(contents.get_data() if contents is not None else b"")
    form.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): RectangleObject(box),
    })
    resources = page.get("/Resources")
    form[NameObject("/Resources")] = (DictionaryObject() if resources is None
                                      else resources.clone(writer))
    # e.g., the transparency group of the page, which blends its content
    if "/Group" in page:
        form[NameObject("/Group")] = page["/Group"].clone(writer)
    return writer._add_object(form.flate_encode())


def _slice_content(layout, top, box, rotation, options):
    """The content stream of a page of paper that shows a slice of a page."""
    paper_width, paper_height = paper_size(options)
    margin = options.margin * MM
    scale = layout.scale
    clip = (margin, margin, paper_width - 2 * margin, paper_height - 2 * margin)
    # the top of the slice at the top of the paper within the margins
    place = (scale, 0, 0, scale, margin + layout.left,
             paper_height - margin - (layout.height - top) * scale)
    return "q\n{} re W n\n{} cm\n{} cm\n/Page Do\nQ\n".format(
        " ".join(map(_number, clip)), " ".join(map(_number, place)),
        " ".join(map(_number, _rotation_matrix(box, rotation)))).encode()


def read_pdf(data):
    """Return a reader of the PDF (bytes)."""
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise ValueError("The PDF is protected with a password")
    return reader


def split_pdf(data, options=Options(), reader: Optional[PdfReader] = None):
    """Split the pages of a PDF (bytes) onto pages of paper and return the
    new PDF and the layout of each page."""
    reader = reader or read_pdf(data)
    paper_width, paper_height = paper_size(options)
    writer = PdfWriter()
    layouts = []
    for _page in reader.pages:
        box, rotation = _page_box(_page)
        layout = layout_page(*_shown_size(box, rotation), options)
        layouts.append(layout)
        form = _form_xobject(writer, _page, box)
        for _top, _ in layout.slices:
            paper = writer.add_blank_page(paper_width, paper_height)
            paper[NameObject("/Resources")] = DictionaryObject({
                NameObject("/XObject"): DictionaryObject({
                    NameObject("/Page"): form})})
            content = DecodedStreamObject()
            content.set_data(_slice_content(layout, _top, box, rotation, options))
            paper.replace_contents(content)
    title = reader.metadata.title if reader.metadata else None
    if title:
        writer.add_metadata({"/Title": title})
    out = io.BytesIO()
    writer.write(out)
    return Result(out.getvalue(), layouts)
