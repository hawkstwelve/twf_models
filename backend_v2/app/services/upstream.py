from __future__ import annotations

from typing import Iterable
import socket

try:
    import requests
except Exception:  # pragma: no cover - optional dependency in some contexts
    requests = None  # type: ignore[assignment]


_HTTP_NOT_READY_STATUS = {404, 416}


def _iter_exception_chain(exc: BaseException) -> Iterable[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        next_exc = current.__cause__ or current.__context__
        current = next_exc if isinstance(next_exc, BaseException) else None


def _http_status_from_exception(exc: BaseException) -> int | None:
    for candidate in _iter_exception_chain(exc):
        response = getattr(candidate, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        status = getattr(candidate, "status", None)
        if isinstance(status, int):
            return status
    return None


def _has_timeout_exception(exc: BaseException) -> bool:
    timeout_types: tuple[type[BaseException], ...] = (TimeoutError, socket.timeout)
    if requests is not None:
        timeout_types = timeout_types + (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ReadTimeout,
        )
    return any(isinstance(candidate, timeout_types) for candidate in _iter_exception_chain(exc))


def _exception_name_matches(exc: BaseException, names: set[str]) -> bool:
    for candidate in _iter_exception_chain(exc):
        if type(candidate).__name__ in names:
            return True
    return False


def _message_indicates_not_ready(message: str) -> bool:
    text = message.lower()
    patterns = [
        "upstream not ready",
        "grib2 file not found",
        "herbie did not return a grib2 path",
        "could not resolve latest hrrr cycle",
        "could not resolve latest gfs cycle",
        "index not ready",
        "idx missing",
        "no index file was found",
        "cannot open index file",
        "download the full file first",
        "inventory not found",
        "no inventory",
        "index_as_dataframe",
        "no valid message found",
        "end of resource reached when reading message",
        "premature end of file",
        "http 404",
        "404 client error",
        "http 416",
        "416 client error",
        "status code 404",
        "status code 416",
        "read timed out",
        "connect timeout",
        "timeout",
    ]
    return any(pattern in text for pattern in patterns)


def is_upstream_not_ready_error(exc: BaseException | str) -> bool:
    if isinstance(exc, str):
        return _message_indicates_not_ready(exc)

    status_code = _http_status_from_exception(exc)
    if status_code in _HTTP_NOT_READY_STATUS:
        return True

    if _has_timeout_exception(exc):
        return True

    if isinstance(exc, EOFError):
        return True

    if _exception_name_matches(exc, {"PrematureEndOfFileError"}):
        return True

    return _message_indicates_not_ready(str(exc))
