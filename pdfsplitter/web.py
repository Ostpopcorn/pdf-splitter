"""Bridge between the web app in the `web` folder and pdfsplitter. The web app
runs this module in the browser with Pyodide and exchanges JSON strings with
it, and PDFs as bytes."""
import json
from dataclasses import asdict, fields

from .split import (MM, PAPERS, Options, count_annotations, layout_page,
                    max_overlap, page_sizes, paper_size, read_pdf, split_pdf)

_OPTIONS = {_field.name: _field.type for _field in fields(Options)}


def defaults():
    """Return the default options and the papers of the web app."""
    return json.dumps({"options": asdict(Options()), "papers": PAPERS})


def _bytes(data):
    """Bytes from Python, or from a Uint8Array of the web app."""
    return data.to_bytes() if hasattr(data, "to_bytes") else bytes(data)


def _options(request):
    options = {}
    for _key, _value in request.get("options", {}).items():
        if _key == "paper":
            options[_key] = str(_value)
        elif _key in _OPTIONS:
            options[_key] = float(_value)
    return Options(**options)


def read(data):
    """Return the size of each page of a PDF in points, as it is shown, its
    title, and the number of its annotations that are shown, or an
    error."""
    data = _bytes(data)
    if b"%PDF-" not in data[:1024]:
        return json.dumps({"error": "It is not a PDF."})
    try:
        reader = read_pdf(data)
        sizes = page_sizes(reader)
        title = reader.metadata.title if reader.metadata else None
        annotations = count_annotations(reader)
    except Exception as err:  # pylint: disable=broad-except
        # e.g., a broken PDF, or one protected with a password
        return json.dumps({"error": "Could not read the PDF: {}".format(err)})
    if not sizes:
        return json.dumps({"error": "The PDF has no pages."})
    return json.dumps({"pages": sizes, "title": title or None,
                       "annotations": annotations})


def plan(request_json):
    """Return the paper and the layout of the pages of a request, each page
    with its width and height in points, or an error. The slices are in
    points from the top of the page. The paper, its margin, the overlap, and
    the space on the left of a page that is shrunk are in points on the
    paper."""
    request = json.loads(request_json)
    try:
        options = _options(request)
        width, height = paper_size(options)
        layouts = [layout_page(_width, _height, options)
                   for _width, _height in request["pages"]]
    except ValueError as err:
        return json.dumps({"error": str(err)})
    return json.dumps({
        "paper": [width, height],
        "margin": options.margin * MM,
        "overlap": options.overlap * MM,
        "max_overlap": max_overlap(options),
        "pages": [{"scale": _layout.scale, "slices": _layout.slices,
                   "left": _layout.left} for _layout in layouts],
    })


def split(data, request_json):
    """Return the new PDF (bytes) of a PDF and the options of a request."""
    return split_pdf(_bytes(data), _options(json.loads(request_json))).data
