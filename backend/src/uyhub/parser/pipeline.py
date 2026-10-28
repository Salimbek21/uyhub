"""Prefilter, extract, normalise — the whole parser as one pure function.

Nothing here touches the database, Redis or the network. That is what lets the
golden-set evaluation run the real pipeline rather than an approximation of it,
and what lets every rule be tested on a string.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from uyhub.core.config import Settings, get_settings
from uyhub.models.enums import RawMessageStatus
from uyhub.parser.extractor import Extractor, RegexExtractor
from uyhub.parser.prefilter import PrefilterResult, prefilter
from uyhub.parser.schema import Extraction


@dataclass(frozen=True, slots=True)
class ParseResult:
    """What the parser decided about one post."""

    status: RawMessageStatus
    extraction: Extraction | None
    prefilter_result: PrefilterResult
    extractor_name: str

    @property
    def rejected(self) -> bool:
        return self.status in (
            RawMessageStatus.REJECTED_PREFILTER,
            RawMessageStatus.REJECTED_LLM,
        )

    @property
    def reject_reason(self) -> str | None:
        if self.prefilter_result.reason is not None:
            return self.prefilter_result.reason.value
        return self.extraction.reject_reason if self.extraction else None


def default_extractor(settings: Settings | None = None) -> Extractor:
    """The extractor this deployment runs.

    Only one today. When ``LLM_ENABLED`` turns on, this is the single place
    that changes (docs/DECISIONS.md P.4).
    """
    cfg = settings or get_settings()
    if cfg.llm_enabled:  # pragma: no cover - the LLM extractor is a later phase
        msg = "LLM_ENABLED is set but no LLM extractor is built yet"
        raise NotImplementedError(msg)
    return RegexExtractor()


def parse(
    text: str,
    *,
    photo_count: int = 0,
    source_trust: float = 1.0,
    uzs_per_usd: Decimal | None = None,
    extractor: Extractor | None = None,
    settings: Settings | None = None,
) -> ParseResult:
    """Run one post through the parser."""
    from uyhub.parser.normalize import normalize

    cfg = settings or get_settings()
    chosen = extractor or default_extractor(cfg)

    verdict = prefilter(text, has_photos=photo_count > 0)
    if not verdict.accepted:
        return ParseResult(
            status=RawMessageStatus.REJECTED_PREFILTER,
            extraction=None,
            prefilter_result=verdict,
            extractor_name=chosen.name,
        )

    raw = chosen.extract(text, has_photos=photo_count > 0)
    extraction = normalize(
        raw,
        text=text,
        photo_count=photo_count,
        source_trust=source_trust,
        uzs_per_usd=uzs_per_usd,
        settings=cfg,
    )

    status = RawMessageStatus.PARSED if extraction.is_listing else RawMessageStatus.REJECTED_LLM
    return ParseResult(
        status=status,
        extraction=extraction,
        prefilter_result=verdict,
        extractor_name=chosen.name,
    )
