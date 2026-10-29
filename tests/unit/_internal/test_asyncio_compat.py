"""Tests for asyncio compatibility utilities.

Tests the _wait_with_timeout compatibility function that abstracts timeout
handling across Python 3.10 and 3.11+.
"""

import asyncio

import pytest

from hamilton_venus._internal._asyncio_compat import _wait_with_timeout


class TestWaitWithTimeout:
    """Tests for _wait_with_timeout function."""

    @pytest.mark.asyncio
    async def test_wait_with_timeout_succeeds_within_timeout(self):
        """Test that awaitable completes successfully within timeout."""

        async def quick_task():
            await asyncio.sleep(0.01)
            return "success"

        result = await _wait_with_timeout(quick_task(), timeout=1.0)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_wait_with_timeout_with_none_timeout_no_deadline(self):
        """Test that None timeout waits indefinitely without timeout."""

        async def quick_task():
            await asyncio.sleep(0.01)
            return "success"

        result = await _wait_with_timeout(quick_task(), timeout=None)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_wait_with_timeout_exceeds_timeout(self):
        """Test that TimeoutError is raised when timeout is exceeded."""

        async def slow_task():
            await asyncio.sleep(10.0)
            return "success"

        with pytest.raises(asyncio.TimeoutError):
            await _wait_with_timeout(slow_task(), timeout=0.01)

    @pytest.mark.asyncio
    async def test_wait_with_timeout_zero_timeout_raises_immediately(self):
        """Test that timeout=0 raises TimeoutError immediately."""

        async def task():
            await asyncio.sleep(0.1)
            return "success"

        with pytest.raises(asyncio.TimeoutError):
            await _wait_with_timeout(task(), timeout=0)

    @pytest.mark.asyncio
    async def test_wait_with_timeout_negative_timeout_raises_immediately(self):
        """Test that negative timeout raises TimeoutError immediately."""

        async def task():
            await asyncio.sleep(0.1)
            return "success"

        with pytest.raises(asyncio.TimeoutError):
            await _wait_with_timeout(task(), timeout=-1.0)

    @pytest.mark.asyncio
    async def test_wait_with_timeout_preserves_awaitable_exception(self):
        """Test that exceptions from awaitable are preserved."""

        async def failing_task():
            raise ValueError("Task failed")

        with pytest.raises(ValueError, match="Task failed"):
            await _wait_with_timeout(failing_task(), timeout=1.0)

    @pytest.mark.asyncio
    async def test_wait_with_timeout_none_preserves_exception(self):
        """Test that exceptions are preserved with None timeout."""

        async def failing_task():
            raise ValueError("Task failed")

        with pytest.raises(ValueError, match="Task failed"):
            await _wait_with_timeout(failing_task(), timeout=None)
