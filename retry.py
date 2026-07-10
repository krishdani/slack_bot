"""A small retry helper shared by the Slack and OpenAI call sites.

Kept deliberately generic: the caller decides which exceptions are worth
retrying and, when the remote service tells us how long to wait (Slack's
``Retry-After`` header), how long to sleep. Everything is logged so a flaky
dependency shows up in the logs rather than as silent data loss.
"""

import logging
import time

logger = logging.getLogger("tpf-community-bot.retry")


def with_retry(
    operation,
    *,
    attempts=3,
    base_delay=0.5,
    max_delay=8.0,
    retriable=lambda exc: True,
    delay_hint=lambda exc: None,
    label="operation",
):
    """Call ``operation()``, retrying transient failures with exponential backoff.

    Args:
        operation: Zero-argument callable to invoke.
        attempts: Total number of tries, including the first one.
        base_delay: Seconds to wait after the first failure; doubles each retry.
        max_delay: Ceiling on the computed backoff.
        retriable: fn(exc) -> bool. Return False to fail fast (e.g. a bad token,
            which no amount of retrying will fix).
        delay_hint: fn(exc) -> float | None. A server-supplied wait, which wins
            over the computed backoff when present.
        label: Name used in log lines.

    Returns:
        Whatever ``operation()`` returns.

    Raises:
        The last exception, once attempts are exhausted or it is not retriable.
    """
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 — the caller classifies via `retriable`
            last_error = exc

            # Fail fast on errors retrying can't fix (bad token, bad request).
            if not retriable(exc):
                logger.error(
                    "retry_abandoned label=%s attempt=%d/%d reason=not_retriable error=%s",
                    label, attempt, attempts, exc,
                )
                raise

            if attempt == attempts:
                break

            hint = delay_hint(exc)
            delay = hint if hint is not None else min(base_delay * 2 ** (attempt - 1), max_delay)
            logger.warning(
                "retry label=%s attempt=%d/%d delay=%.2fs error=%s",
                label, attempt, attempts, delay, exc,
            )
            time.sleep(delay)

    logger.error(
        "retry_exhausted label=%s attempts=%d error=%s", label, attempts, last_error
    )
    raise last_error
