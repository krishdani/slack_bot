"""Off-request execution for slow work (AI calls, Slack DMs).

Slack retries any event we don't acknowledge within ~3 seconds, and an AI call
plus a DM can easily exceed that. So the route validates, enqueues, and returns
200 immediately; the real work happens on this pool.

A task that raises must never take the worker (or the app) down, so every task
is wrapped: exceptions are logged with the task name and swallowed.
"""

import atexit
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import config

logger = logging.getLogger("tpf-community-bot.background")

_executor = ThreadPoolExecutor(
    max_workers=config.BACKGROUND_WORKERS,
    thread_name_prefix="tpf-bg",
)


def _run(fn, args, kwargs):
    """Run one task, logging its duration and containing any exception."""
    name = getattr(fn, "__name__", repr(fn))
    started = time.perf_counter()
    try:
        fn(*args, **kwargs)
    except Exception:  # noqa: BLE001 — a background task must never kill the worker
        logger.exception(
            "task_failed task=%s duration_ms=%d",
            name, (time.perf_counter() - started) * 1000,
        )
    else:
        logger.info(
            "task_done task=%s duration_ms=%d",
            name, (time.perf_counter() - started) * 1000,
        )


def submit(fn, *args, **kwargs):
    """Queue ``fn(*args, **kwargs)`` on a worker thread. Never raises."""
    try:
        _executor.submit(_run, fn, args, kwargs)
    except RuntimeError:
        # Raised only if the interpreter is shutting down and the pool is closed.
        logger.warning("submit_rejected task=%s (executor shut down)",
                       getattr(fn, "__name__", repr(fn)))


@atexit.register
def _shutdown():
    """Let in-flight DMs finish when the process is asked to stop."""
    _executor.shutdown(wait=True)
