"""Split the tall pages of a PDF onto pages of paper with an overlap.

    python -m pdfsplitter notes.pdf                 # writes notes-a4.pdf
    python -m pdfsplitter notes.pdf --overlap 30 --paper letter -o out.pdf
"""
import argparse
import os
import sys

from .split import PAPERS, Options, count_annotations, read_pdf, split_pdf


def main(argv=None):
    defaults = Options()
    parser = argparse.ArgumentParser(
        prog="pdf-splitter", description=__doc__.splitlines()[0])
    parser.add_argument("input", help="The PDF to split")
    parser.add_argument("-o", "--output",
                        help="The new PDF (default: INPUT-PAPER.pdf)")
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
    args = parser.parse_args(argv)
    output = args.output or "{}-{}.pdf".format(
        os.path.splitext(args.input)[0], args.paper)
    if os.path.abspath(output) == os.path.abspath(args.input):
        parser.error("The output would overwrite the input")
    with open(args.input, "rb") as _file:
        data = _file.read()
    try:
        reader = read_pdf(data)
        result = split_pdf(data, Options(args.paper, args.overlap, args.margin,
                                         args.shrink), reader)
    except ValueError as err:
        parser.exit(1, "{}: error: {}\n".format(parser.prog, err))
    with open(output, "wb") as _file:
        _file.write(result.data)
    split = sum(len(_layout.slices) > 1 for _layout in result.layouts)
    print("Wrote {} with {} pages from {} pages, of which {} split".format(
        output, result.pages, len(result.layouts), split), file=sys.stderr)
    annotations = count_annotations(reader)
    if annotations:
        print("{} annotations, e.g., comments, are not in the split PDF"
              .format(annotations), file=sys.stderr)


if __name__ == "__main__":
    main()
