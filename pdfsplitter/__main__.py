"""Split the tall pages of PDFs onto pages of paper with an overlap.

    python -m pdfsplitter notes.pdf                 # writes notes-a4.pdf
    python -m pdfsplitter notes.pdf --overlap 30 --paper letter -o out.pdf
    python -m pdfsplitter notes.pdf photo.jpg -o all.pdf  # combines them
    python -m pdfsplitter plan.pdf --poster 100 --margin 5  # plan-poster-a4.pdf
"""
import argparse
import os
import sys

from .image import jpeg_pdf
from .split import PAPERS, Options, count_annotations, read_pdf, split_pdfs


def main(argv=None):
    defaults = Options()
    parser = argparse.ArgumentParser(
        prog="pdf-splitter", description=__doc__.splitlines()[0])
    parser.add_argument("inputs", nargs="+", metavar="input",
                        help="A PDF or a JPEG image to split. The pages of "
                        "several are combined, one after another.")
    parser.add_argument("-o", "--output", help="The new PDF (default: "
                        "INPUT-PAPER.pdf, after the first input)")
    parser.add_argument("--paper", default=defaults.paper, choices=PAPERS,
                        type=str.lower,
                        help="The size of the paper (default: %(default)s)")
    parser.add_argument("--overlap", default=defaults.overlap, type=float,
                        metavar="MM", help="The end of a page that is repeated "
                        "at the top of the next one (default: %(default)g mm)")
    parser.add_argument("--margin", default=defaults.margin, type=float,
                        metavar="MM", help="The margin on each side of the "
                        "paper (default: %(default)g mm)")
    parser.add_argument("--shrink", default=defaults.shrink, type=float,
                        metavar="PERCENT", help="Make a page up to this much "
                        "smaller if it then needs fewer pages, e.g., a page "
                        "that is a bit too long (default: %(default)g %%)")
    parser.add_argument("--poster", type=float, metavar="PERCENT",
                        help="Make each page a poster at this scale, on "
                        "rows and columns of pages, which overlap. Print it "
                        "at actual size, and set the margin to the edge "
                        "where your printer does not print.")
    parser.add_argument("--center", action="store_true",
                        help="Put a poster in the middle of its pages, "
                        "instead of at their top left")
    parser.add_argument("--crop", action="store_true",
                        help="Leave out the margins: each page is the paper "
                        "within the margins, which the printer places on "
                        "the paper")
    parser.add_argument("--no-turn", dest="turn", action="store_false",
                        help="Keep the paper upright, also for wide pages "
                        "and posters that would need fewer pages turned")
    args = parser.parse_args(argv)
    output = args.output or "{}-{}{}.pdf".format(
        os.path.splitext(args.inputs[0])[0],
        "poster-" if args.poster is not None else "", args.paper)
    if any(os.path.abspath(output) == os.path.abspath(_input)
           for _input in args.inputs):
        parser.error("The output would overwrite an input")
    readers = []
    for _input in args.inputs:
        with open(_input, "rb") as _file:
            data = _file.read()
        try:
            if data[:3] == b"\xff\xd8\xff":  # a JPEG image
                data = jpeg_pdf(data)
            readers.append(read_pdf(data))
        except Exception as err:  # pylint: disable=broad-except
            parser.exit(1, "{}: error: {}: {}\n".format(parser.prog, _input,
                                                        err))
    try:
        result = split_pdfs(readers, Options(
            args.paper, args.overlap, args.margin, args.shrink, args.turn,
            args.poster is not None,
            100 if args.poster is None else args.poster, args.center,
            args.crop))
    except ValueError as err:
        parser.exit(1, "{}: error: {}\n".format(parser.prog, err))
    with open(output, "wb") as _file:
        _file.write(result.data)
    split = sum(len(_layout.slices) > 1 for _layout in result.layouts)
    print("Wrote {} with {} pages from {} pages, of which {} split".format(
        output, result.pages, len(result.layouts), split), file=sys.stderr)
    annotations = sum(map(count_annotations, readers))
    if annotations:
        print("{} annotations, e.g., comments, are not in the split PDF"
              .format(annotations), file=sys.stderr)


if __name__ == "__main__":
    main()
