"""The Telegram collector (SPEC section 4).

Reads the sources we have joined and writes an immutable copy of every post to
``raw_messages`` plus its photos to MinIO, then announces each one on
``stream:raw``. It never sends, forwards, reacts or edits.
"""

from uyhub.collector.types import DeletedMessages, IncomingMedia, IncomingMessage, ResolvedChat

__all__ = ["DeletedMessages", "IncomingMedia", "IncomingMessage", "ResolvedChat"]
