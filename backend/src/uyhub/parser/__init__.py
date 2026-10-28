"""Turning Telegram posts into structured listings (SPEC sections 5 and 6).

Two stages: a cheap prefilter that rejects what is obviously not a listing, and
an extractor that reads the fields out of what survives. The extractor is
regex-based today and LLM-backed later, behind one interface
(docs/DECISIONS.md P.4).
"""

from uyhub.parser.pipeline import ParseResult, parse
from uyhub.parser.schema import Extraction, RawExtraction

__all__ = ["Extraction", "ParseResult", "RawExtraction", "parse"]
