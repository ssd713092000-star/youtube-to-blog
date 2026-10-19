import asyncio
import sys

import pytest


@pytest.fixture(scope="session")
def event_loop_policy():
    # psycopg's async driver needs a selector loop on Windows.
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()
