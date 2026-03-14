"""
Improvement #1: Exponential Backoff Retry with Error Classification

Inspired by: OpenHands (openhands/controller/agent_controller.py)
Addresses: Weakness #1 — no retry on LLM failures

Integration:
    In Agent._get_llm_response(), wrap the LLM call:

    async def _get_llm_response(self, messages, tools):
        return await retry_with_backoff(
            lambda: self.llm.complete(messages, tools),
            config=RetryConfig(max_retries=3),
            on_retry=lambda attempt, e, cat: self._emit(Event(
                type=EventType.ERROR,
                timestamp=datetime.now(),
                data={"error": str(e), "retry_attempt": attempt, "category": cat.value},
            ))
        )
"""

import asyncio
import logging
import random
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    """Classification of LLM errors for retry strategy."""
    TRANSIENT = "transient"       # 429, 500, 502, 503, 504 -> retry
    AUTH = "auth"                 # 401, 403 -> don't retry
    CONTEXT_OVERFLOW = "context"  # context window exceeded -> condense & retry
    MALFORMED = "malformed"       # bad JSON from LLM -> retry with nudge
    FATAL = "fatal"              # everything else -> don't retry


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True


def classify_error(error: Exception, status_code: Optional[int] = None) -> ErrorCategory:
    """Classify an error into a category for retry decisions.

    Args:
        error: The exception that occurred.
        status_code: HTTP status code if available.

    Returns:
        ErrorCategory indicating how to handle the error.
    """
    error_msg = str(error).lower()

    if status_code:
        if status_code == 429:
            return ErrorCategory.TRANSIENT
        if status_code in (401, 403):
            return ErrorCategory.AUTH
        if status_code in (500, 502, 503, 504):
            return ErrorCategory.TRANSIENT

    if "context" in error_msg and ("window" in error_msg or "length" in error_msg or "exceed" in error_msg):
        return ErrorCategory.CONTEXT_OVERFLOW
    if "rate" in error_msg and "limit" in error_msg:
        return ErrorCategory.TRANSIENT
    if "timeout" in error_msg or "timed out" in error_msg:
        return ErrorCategory.TRANSIENT
    if "json" in error_msg and ("decode" in error_msg or "parse" in error_msg):
        return ErrorCategory.MALFORMED
    if "auth" in error_msg or "key" in error_msg or "unauthorized" in error_msg:
        return ErrorCategory.AUTH

    return ErrorCategory.FATAL


async def retry_with_backoff(
    func: Callable,
    config: RetryConfig = RetryConfig(),
    on_retry: Optional[Callable[[int, Exception, ErrorCategory], None]] = None,
) -> Any:
    """Execute an async function with exponential backoff retry.

    Only retries on TRANSIENT and MALFORMED errors.
    CONTEXT_OVERFLOW is raised immediately for the caller to handle.
    AUTH and FATAL errors are raised immediately.

    Args:
        func: Async callable to execute.
        config: Retry configuration.
        on_retry: Optional callback(attempt, error, category) on each retry.

    Returns:
        The result of the successful function call.

    Raises:
        The last exception if all retries are exhausted, or non-retryable errors.
    """
    last_error: Optional[Exception] = None

    for attempt in range(config.max_retries + 1):
        try:
            return await func()
        except Exception as e:
            last_error = e
            status_code = getattr(e, "status_code", None) or getattr(
                getattr(e, "response", None), "status_code", None
            )
            category = classify_error(e, status_code)

            if category in (ErrorCategory.AUTH, ErrorCategory.FATAL, ErrorCategory.CONTEXT_OVERFLOW):
                raise

            if attempt >= config.max_retries:
                raise

            delay = min(
                config.base_delay * (config.exponential_base ** attempt),
                config.max_delay,
            )
            if config.jitter:
                delay *= 0.5 + random.random()

            if on_retry:
                on_retry(attempt + 1, e, category)

            logger.warning(
                f"Retry {attempt + 1}/{config.max_retries} after {delay:.1f}s "
                f"({category.value}): {e}"
            )
            await asyncio.sleep(delay)

    raise last_error  # type: ignore[misc]
