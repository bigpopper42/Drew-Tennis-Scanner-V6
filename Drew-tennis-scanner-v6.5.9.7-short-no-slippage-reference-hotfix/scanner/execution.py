"""Compatibility import for the rebuilt Polymarket executor."""

from .polymarket_executor import (  # noqa: F401
    ExecutionConfig,
    ExecutionResult,
    LONG_SIDE,
    SHORT_SIDE,
    PolymarketExecutionEngine,
)

__all__ = [
    "ExecutionConfig",
    "ExecutionResult",
    "LONG_SIDE",
    "SHORT_SIDE",
    "PolymarketExecutionEngine",
]
