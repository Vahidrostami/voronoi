"""Paper generator package — processes experiment results into a complete LaTeX paper."""

from .results_analyzer import ResultsAnalyzer
from .figure_generator import FigureGenerator
from .table_generator import TableGenerator
from .latex_writer import LaTeXWriter

__all__ = ["ResultsAnalyzer", "FigureGenerator", "TableGenerator", "LaTeXWriter"]
