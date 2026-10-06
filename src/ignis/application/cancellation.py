"""Settle ownership-sensitive operations before delivering cancellation to their caller."""

import asyncio
from typing import Any, Coroutine, TypeVar

_Result = TypeVar("_Result")


async def await_settled(operation: Coroutine[Any, Any, _Result]) -> _Result:
    worker = asyncio.create_task(operation)
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # A repeated cancellation must not release ownership while the original operation
        # can still commit. Consume its outcome, then preserve the caller's cancellation.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not worker.cancelled():
            worker.exception()
        raise
