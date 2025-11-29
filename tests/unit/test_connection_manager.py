"""
Unit tests for ConnectionManager (Socket Pool & Session Management).

These tests verify the critical socket and session lifecycle management that
prevents socket exhaustion during mode transitions (Weather ↔ Setup Mode).

Key invariants tested:
1. Socket pool is created once and reused (not recreated on mode transitions)
2. Sessions are properly closed when modes change
3. _close_session() preserves the socket pool
4. _invalidate_socket_pool() is only used for shutdown
5. Multiple mode transition cycles don't exhaust sockets

The socket exhaustion bug manifested as:
- "Out of sockets" error on 3rd entry to Setup Mode
- Each mode transition was creating a new socket pool
- lwIP socket descriptors were not being released by GC

See tests.unit for instructions on running tests.

Note: Type ignores are used extensively because we're assigning mock objects
to typed fields in ConnectionManager. This is standard practice for unit tests.
"""

from core.app_typing import Any, cast
from managers.connection_manager import ConnectionManager
from tests.unit import TestCase


class MockSocketPool:
    """Mock socket pool that tracks creation count."""

    _creation_count = 0

    def __init__(self, radio: Any) -> None:
        MockSocketPool._creation_count += 1
        self.radio = radio
        self.instance_id = MockSocketPool._creation_count

    @classmethod
    def reset_count(cls) -> None:
        cls._creation_count = 0

    @classmethod
    def get_count(cls) -> int:
        return cls._creation_count


class MockSocket:
    """Mock socket that tracks close calls."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class MockSession:
    """Mock HTTP session with socket tracking."""

    def __init__(self, pool: Any, ssl_context: Any) -> None:
        self.pool = pool
        self.ssl_context = ssl_context
        self._socket: MockSocket | None = MockSocket()
        self.closed = False


class MockRadio:
    """Mock WiFi radio for testing."""

    def __init__(self) -> None:
        self.connected = True
        self.ipv4_address = "10.0.0.1"
        self.enabled = True


class TestConnectionManagerSocketPoolLifecycle(TestCase):
    """Test socket pool creation and reuse - prevents socket exhaustion."""

    def setUp(self) -> None:
        """Reset singleton and mocks before each test."""
        ConnectionManager._instance = None
        MockSocketPool.reset_count()

    def tearDown(self) -> None:
        """Clean up singleton after each test."""
        ConnectionManager._instance = None

    def test_socket_pool_created_once(self) -> None:
        """
        Socket pool should be created only once, not on every call.

        This was the root cause of socket exhaustion - each mode transition
        created a new pool, exhausting lwIP socket descriptors.
        """
        # Create manager with mock radio
        manager = ConnectionManager.__new__(ConnectionManager)
        manager._radio = MockRadio()  # type: ignore[assignment]
        manager._socket_pool = None
        manager.session = None
        manager.logger = _MockLogger()  # type: ignore[assignment]

        # Patch socketpool.SocketPool
        import managers.connection_manager as cm_module

        original_socketpool = getattr(cm_module, "socketpool", None)
        mock_socketpool = type("MockSocketPoolModule", (), {"SocketPool": MockSocketPool})()
        cm_module.socketpool = mock_socketpool

        try:
            # First call creates pool
            pool1 = manager.get_socket_pool()
            self.assertEqual(MockSocketPool.get_count(), 1, "First call should create pool")

            # Second call reuses pool
            pool2 = manager.get_socket_pool()
            self.assertEqual(MockSocketPool.get_count(), 1, "Second call should NOT create new pool")
            self.assertIs(pool1, pool2, "Should return same pool instance")

            # Many calls should still reuse
            for _ in range(10):
                manager.get_socket_pool()
            self.assertEqual(MockSocketPool.get_count(), 1, "Multiple calls should NOT create new pools")

        finally:
            if original_socketpool:
                cm_module.socketpool = original_socketpool

    def test_close_session_preserves_pool(self) -> None:
        """
        _close_session() should close the session but NOT invalidate the pool.

        This is critical for mode transitions - we want to release the session's
        socket resources but keep the pool for reuse.
        """
        manager = ConnectionManager.__new__(ConnectionManager)
        manager._radio = MockRadio()  # type: ignore[assignment]
        manager._socket_pool = MockSocketPool(manager._radio)  # type: ignore[assignment]
        manager.session = MockSession(manager._socket_pool, None)  # type: ignore[assignment]
        manager.logger = _MockLogger()  # type: ignore[assignment]

        original_pool = manager._socket_pool
        original_session = manager.session

        # Close session
        manager._close_session("test reason")

        # Session should be cleared
        self.assertIsNone(manager.session, "Session should be None after close")

        # Pool should be PRESERVED (this was the bug fix)
        self.assertIsNotNone(manager._socket_pool, "Pool should NOT be cleared by _close_session")
        self.assertIs(manager._socket_pool, original_pool, "Pool should be same instance")

        # Session's socket should be closed
        mock_session = cast(MockSession, original_session)
        socket_closed = mock_session._socket is None or mock_session._socket.closed
        self.assertTrue(socket_closed, "Session socket should be closed")

    def test_invalidate_pool_clears_both(self) -> None:
        """
        _invalidate_socket_pool() should clear both session AND pool.

        This should ONLY be called during shutdown, not during mode transitions.
        """
        manager = ConnectionManager.__new__(ConnectionManager)
        manager._radio = MockRadio()  # type: ignore[assignment]
        manager._socket_pool = MockSocketPool(manager._radio)  # type: ignore[assignment]
        manager.session = MockSession(manager._socket_pool, None)  # type: ignore[assignment]
        manager.logger = _MockLogger()  # type: ignore[assignment]

        # Invalidate pool (shutdown scenario)
        manager._invalidate_socket_pool("shutdown")

        # Both should be cleared
        self.assertIsNone(manager.session, "Session should be None after invalidate")
        self.assertIsNone(manager._socket_pool, "Pool should be None after invalidate")

    def test_close_session_is_idempotent(self) -> None:
        """Calling _close_session() multiple times should be safe."""
        manager = ConnectionManager.__new__(ConnectionManager)
        manager._radio = MockRadio()  # type: ignore[assignment]
        manager._socket_pool = MockSocketPool(manager._radio)  # type: ignore[assignment]
        manager.session = None  # Already None
        manager.logger = _MockLogger()  # type: ignore[assignment]

        # Should not raise
        manager._close_session("first")
        manager._close_session("second")
        manager._close_session("third")

        # Pool still preserved
        self.assertIsNotNone(manager._socket_pool)


class TestConnectionManagerModeTransitions(TestCase):
    """
    Test socket pool behavior during mode transitions.

    These tests simulate the Weather → Setup → Weather cycle that
    was causing socket exhaustion.
    """

    def setUp(self) -> None:
        """Reset singleton and mocks before each test."""
        ConnectionManager._instance = None
        MockSocketPool.reset_count()

    def tearDown(self) -> None:
        """Clean up singleton after each test."""
        ConnectionManager._instance = None

    def test_mode_transition_reuses_pool(self) -> None:
        """
        Simulates: Weather Mode → Setup Mode → Weather Mode

        The socket pool should be reused, not recreated.
        """
        manager = ConnectionManager.__new__(ConnectionManager)
        manager._radio = MockRadio()  # type: ignore[assignment]
        manager._socket_pool = None
        manager.session = None
        manager.logger = _MockLogger()  # type: ignore[assignment]

        # Patch socketpool
        import managers.connection_manager as cm_module

        original_socketpool = getattr(cm_module, "socketpool", None)
        mock_socketpool = type("MockSocketPoolModule", (), {"SocketPool": MockSocketPool})()
        cm_module.socketpool = mock_socketpool

        try:
            # 1. Weather Mode starts - creates pool
            pool1 = manager.get_socket_pool()
            self.assertEqual(MockSocketPool.get_count(), 1)

            # Simulate session creation for weather requests
            manager.session = MockSession(pool1, None)  # type: ignore[assignment]

            # 2. Enter Setup Mode - close session, reuse pool
            manager._close_session("entering setup mode")
            pool2 = manager.get_socket_pool()  # Setup mode gets pool for DNS/HTTP
            self.assertEqual(MockSocketPool.get_count(), 1, "Setup mode should reuse pool")
            self.assertIs(pool1, pool2)

            # 3. Exit Setup Mode - close session
            manager._close_session("exiting setup mode")

            # 4. Weather Mode restarts - should reuse pool
            pool3 = manager.get_socket_pool()
            self.assertEqual(MockSocketPool.get_count(), 1, "Weather mode restart should reuse pool")
            self.assertIs(pool1, pool3)

        finally:
            if original_socketpool:
                cm_module.socketpool = original_socketpool

    def test_three_mode_cycles_no_new_pools(self) -> None:
        """
        Simulate 3 complete mode transition cycles.

        This was the exact failure scenario - "Out of sockets" on 3rd Setup entry.
        With the fix, only 1 pool should ever be created.
        """
        manager = ConnectionManager.__new__(ConnectionManager)
        manager._radio = MockRadio()  # type: ignore[assignment]
        manager._socket_pool = None
        manager.session = None
        manager.logger = _MockLogger()  # type: ignore[assignment]

        # Patch socketpool
        import managers.connection_manager as cm_module

        original_socketpool = getattr(cm_module, "socketpool", None)
        mock_socketpool = type("MockSocketPoolModule", (), {"SocketPool": MockSocketPool})()
        cm_module.socketpool = mock_socketpool

        try:
            for cycle in range(3):
                # Weather Mode
                pool = manager.get_socket_pool()
                manager.session = MockSession(pool, None)  # type: ignore[assignment]

                # Enter Setup Mode
                manager._close_session(f"setup entry cycle {cycle}")
                manager.get_socket_pool()  # DNS/HTTP use pool

                # Exit Setup Mode
                manager._close_session(f"setup exit cycle {cycle}")

            # After 3 complete cycles, still only 1 pool
            self.assertEqual(
                MockSocketPool.get_count(),
                1,
                f"After 3 cycles, should have 1 pool, got {MockSocketPool.get_count()}",
            )

        finally:
            if original_socketpool:
                cm_module.socketpool = original_socketpool


class TestConnectionManagerSessionManagement(TestCase):
    """Test HTTP session lifecycle management."""

    def setUp(self) -> None:
        """Reset singleton before each test."""
        ConnectionManager._instance = None

    def tearDown(self) -> None:
        """Clean up singleton after each test."""
        ConnectionManager._instance = None

    def test_session_socket_closed_on_close_session(self) -> None:
        """Session's internal socket should be closed when session is closed."""
        manager = ConnectionManager.__new__(ConnectionManager)
        manager._radio = MockRadio()  # type: ignore[assignment]
        manager._socket_pool = MockSocketPool(manager._radio)  # type: ignore[assignment]
        manager.logger = _MockLogger()  # type: ignore[assignment]

        # Create session with mock socket
        mock_socket = MockSocket()
        session = MockSession(manager._socket_pool, None)
        session._socket = mock_socket
        manager.session = session  # type: ignore[assignment]

        # Close session
        manager._close_session("test")

        # Socket should be closed
        self.assertTrue(mock_socket.closed, "Session socket should be closed")

    def test_session_without_socket_closes_safely(self) -> None:
        """Session without _socket attribute should close without error."""
        manager = ConnectionManager.__new__(ConnectionManager)
        manager._radio = MockRadio()  # type: ignore[assignment]
        manager._socket_pool = MockSocketPool(manager._radio)  # type: ignore[assignment]
        manager.logger = _MockLogger()  # type: ignore[assignment]

        # Create session without _socket
        session = type("BareSession", (), {})()
        manager.session = session  # type: ignore[assignment]

        # Should not raise
        manager._close_session("test")
        self.assertIsNone(manager.session)

    def test_session_with_none_socket_closes_safely(self) -> None:
        """Session with _socket=None should close without error."""
        manager = ConnectionManager.__new__(ConnectionManager)
        manager._radio = MockRadio()  # type: ignore[assignment]
        manager._socket_pool = MockSocketPool(manager._radio)  # type: ignore[assignment]
        manager.logger = _MockLogger()  # type: ignore[assignment]

        session = MockSession(manager._socket_pool, None)
        session._socket = None
        manager.session = session  # type: ignore[assignment]

        # Should not raise
        manager._close_session("test")
        self.assertIsNone(manager.session)


class _MockLogger:
    """Simple mock logger that accepts all log calls."""

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        pass
