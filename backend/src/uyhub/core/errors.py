"""Base exception types shared by every service."""

from __future__ import annotations


class UyHubError(Exception):
    """Root of every error this application raises deliberately."""


class ConfigError(UyHubError):
    """Configuration is missing or invalid."""


class DependencyUnavailableError(UyHubError):
    """An external dependency (Postgres, Redis, S3, ...) is not reachable.

    Carries the dependency name so readiness probes can report which one failed
    without leaking connection strings.
    """

    def __init__(self, dependency: str, reason: str) -> None:
        self.dependency = dependency
        self.reason = reason
        super().__init__(f"{dependency} unavailable: {reason}")
