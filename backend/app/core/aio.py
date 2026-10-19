import asyncio
import sys
from collections.abc import Callable
from typing import Any


def loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    """psycopg's async driver cannot use the Windows Proactor loop; use a selector loop there."""
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop
    return None


def run(coro: Any) -> Any:
    return asyncio.run(coro, loop_factory=loop_factory())
