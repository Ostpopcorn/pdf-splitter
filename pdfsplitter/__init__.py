"""Split tall pages, e.g., of notes from a reMarkable, onto pages of paper
with an overlap."""
from .split import (MM, PAPERS, Layout, Options, Result, layout_page,
                    max_overlap, paper_size, split_pdf)

__version__ = "0.1.0"

__all__ = ["MM", "PAPERS", "Layout", "Options", "Result", "layout_page",
           "max_overlap", "paper_size", "split_pdf"]
