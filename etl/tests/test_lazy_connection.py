"""The CLI's reconnecting database connection, against a fake asyncpg.

Nothing here touches a database. `asyncpg.connect` is replaced with a factory
that hands out numbered fake connections, so a test can close one and see which
connection the next statement lands on.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import pytest

from pipeline.__main__ import _LazyConnection
from pipeline.errors import SinkError


class FakeConnection:
    def __init__(self, number: int) -> None:
        self.number = number
        self.closed = False
        self.executed: list[str] = []

    def is_closed(self) -> bool:
        return self.closed

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append(query)
        return "OK"

    async def fetchval(self, query: str, *args: Any) -> int:
        self.executed.append(query)
        return self.number

    async def close(self) -> None:
        self.closed = True

    def transaction(self) -> Any:
        @asynccontextmanager
        async def opened() -> AsyncIterator[None]:
            yield None

        return opened()


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[FakeConnection]:
    connections: list[FakeConnection] = []

    async def connect(dsn: str) -> FakeConnection:
        connection = FakeConnection(len(connections) + 1)
        connections.append(connection)
        return connection

    monkeypatch.setattr(asyncpg, "connect", connect)
    return connections


async def test_outside_a_transaction_a_closed_connection_is_replaced(
    opened: list[FakeConnection],
) -> None:
    """The reason the class exists: Neon closes a connection left idle."""
    connection = _LazyConnection("postgres://fake")
    assert await connection.fetchval("SELECT 1") == 1

    opened[0].closed = True

    assert await connection.fetchval("SELECT 1") == 2


async def test_inside_a_transaction_every_call_goes_to_the_pinned_connection(
    opened: list[FakeConnection],
) -> None:
    connection = _LazyConnection("postgres://fake")
    async with connection.transaction():
        await connection.execute("INSERT 1")
        await connection.execute("INSERT 2")

    assert len(opened) == 1
    assert opened[0].executed == ["INSERT 1", "INSERT 2"]


async def test_a_connection_lost_inside_a_transaction_raises_rather_than_reconnecting(
    opened: list[FakeConnection],
) -> None:
    """A reconnect here would autocommit the rest of the transaction on its own."""
    connection = _LazyConnection("postgres://fake")
    with pytest.raises(SinkError, match="inside a transaction"):
        async with connection.transaction():
            await connection.execute("INSERT 1")
            opened[0].closed = True
            await connection.execute("INSERT 2")

    assert len(opened) == 1
    assert opened[0].executed == ["INSERT 1"]


async def test_a_nested_transaction_keeps_the_pin_until_the_outer_one_ends(
    opened: list[FakeConnection],
) -> None:
    connection = _LazyConnection("postgres://fake")
    async with connection.transaction():
        async with connection.transaction():
            await connection.execute("INSERT 1")
        opened[0].closed = True
        with pytest.raises(SinkError):
            await connection.execute("INSERT 2")

    # Once the transaction is over the ordinary reconnect applies again.
    assert await connection.fetchval("SELECT 1") == 2
