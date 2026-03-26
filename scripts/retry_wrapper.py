from __future__ import annotations

import time
from typing import Any, Callable


class APINetworkError(RuntimeError):
    pass


class ContextLengthExceededError(RuntimeError):
    pass


class ModelUnavailableError(RuntimeError):
    pass


class CircuitBreakerOpenError(RuntimeError):
    pass


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, reset_timeout: int = 30):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.opened_at: float | None = None

    def check(self):
        if self.opened_at is None:
            return
        if time.time() - self.opened_at >= self.reset_timeout:
            self.failures = 0
            self.opened_at = None
            return
        raise CircuitBreakerOpenError('Circuit breaker is open; refusing repeated failing calls temporarily.')

    def record_success(self):
        self.failures = 0
        self.opened_at = None

    def record_failure(self):
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = time.time()


def call_with_retry(
    messages: list[dict[str, Any]],
    model: str,
    api_callable: Callable[..., dict[str, Any]],
    *,
    max_attempts: int = 3,
    base_delay: int = 2,
    compress_callable: Callable[[list[dict[str, Any]], str], tuple[list[dict[str, Any]], dict[str, Any]]] | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    **api_kwargs,
):
    retry_count = 0
    compression_meta = None
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        if circuit_breaker:
            circuit_breaker.check()
        try:
            payload = api_callable(messages=messages, model=model, **api_kwargs)
            if circuit_breaker:
                circuit_breaker.record_success()
            return payload, {'retry_count': retry_count, 'compression_meta': compression_meta}
        except ContextLengthExceededError as exc:
            last_error = exc
            if compress_callable is None:
                if circuit_breaker:
                    circuit_breaker.record_failure()
                raise
            messages, compression_meta = compress_callable(messages, model)
            retry_count += 1
            continue
        except APINetworkError as exc:
            last_error = exc
            retry_count += 1
            if circuit_breaker:
                circuit_breaker.record_failure()
            if attempt >= max_attempts:
                break
            time.sleep(min(base_delay ** attempt, 10))
        except Exception as exc:
            last_error = exc
            if circuit_breaker:
                circuit_breaker.record_failure()
            raise

    if last_error:
        raise last_error
    raise RuntimeError('API retry wrapper failed without an explicit error.')
