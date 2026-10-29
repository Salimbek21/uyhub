"""Turning parsed messages into deduplicated listings (SPEC section 7).

The same flat is cross-posted to ten groups; this package decides that those
ten messages are one property, folds each new sighting into the listing without
ever losing information, and announces the result on ``stream:listings``.
"""

from uyhub.dedup.assemble import AssembleResult, assemble
from uyhub.dedup.fingerprint import dedup_key, simhash
from uyhub.dedup.matcher import MatchCandidate, MatchRule, find_match

__all__ = [
    "AssembleResult",
    "MatchCandidate",
    "MatchRule",
    "assemble",
    "dedup_key",
    "find_match",
    "simhash",
]
