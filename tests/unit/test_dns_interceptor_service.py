"""Unit tests for DNSInterceptorService."""

import struct
import unittest
from unittest.mock import MagicMock, patch


class TestDNSInterceptorServicePureFunctions(unittest.TestCase):
    """Test pure helper functions in DNSInterceptorService."""

    def setUp(self) -> None:
        with patch("core.logging_helper.logger"):
            from services.dns_interceptor_service import DNSInterceptorService

            self.service = DNSInterceptorService("192.168.4.1")

    def test_ip_to_bytes_valid(self) -> None:
        result = self.service._ip_to_bytes("192.168.4.1")
        self.assertEqual(result, bytes([192, 168, 4, 1]))

    def test_ip_to_bytes_localhost(self) -> None:
        result = self.service._ip_to_bytes("127.0.0.1")
        self.assertEqual(result, bytes([127, 0, 0, 1]))

    def test_ip_to_bytes_all_zeros(self) -> None:
        result = self.service._ip_to_bytes("0.0.0.0")
        self.assertEqual(result, bytes([0, 0, 0, 0]))

    def test_ip_to_bytes_invalid_format_too_few_parts(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.service._ip_to_bytes("192.168.1")
        self.assertIn("Invalid IP address", str(ctx.exception))

    def test_ip_to_bytes_invalid_format_too_many_parts(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.service._ip_to_bytes("192.168.1.1.1")
        self.assertIn("Invalid IP address", str(ctx.exception))

    def test_ip_to_bytes_non_numeric(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.service._ip_to_bytes("abc.def.ghi.jkl")
        self.assertIn("Invalid IP address", str(ctx.exception))

    def test_encode_domain_name_simple(self) -> None:
        result = self.service._encode_domain_name("example.com")
        # Format: length byte + label, repeated, then null terminator
        expected = b"\x07example\x03com\x00"
        self.assertEqual(result, expected)

    def test_encode_domain_name_subdomain(self) -> None:
        result = self.service._encode_domain_name("www.example.com")
        expected = b"\x03www\x07example\x03com\x00"
        self.assertEqual(result, expected)

    def test_encode_domain_name_empty(self) -> None:
        result = self.service._encode_domain_name("")
        self.assertEqual(result, b"\x00")

    def test_encode_domain_name_truncates_long_label(self) -> None:
        long_label = "a" * 100  # Exceeds 63-char limit
        result = self.service._encode_domain_name(f"{long_label}.com")
        # First label should be truncated to 63 chars
        self.assertEqual(result[0], 63)

    def test_parse_domain_name_simple(self) -> None:
        # Encoded "example.com"
        data = b"\x07example\x03com\x00"
        domain, offset = self.service._parse_domain_name(data, 0)
        self.assertEqual(domain, "example.com")
        self.assertEqual(offset, len(data))

    def test_parse_domain_name_with_compression_pointer(self) -> None:
        # Compression pointer at offset 0xC0 0x0C (points to offset 12)
        data = b"\xc0\x0c"
        domain, offset = self.service._parse_domain_name(data, 0)
        self.assertEqual(domain, "")
        self.assertEqual(offset, 2)

    def test_parse_domain_name_invalid_length(self) -> None:
        # Length byte says 10, but only 3 bytes follow
        data = b"\x0aabc"
        with self.assertRaises(ValueError):
            self.service._parse_domain_name(data, 0)


class TestDNSQueryParsing(unittest.TestCase):
    """Test DNS query parsing."""

    def setUp(self) -> None:
        with patch("core.logging_helper.logger"):
            from services.dns_interceptor_service import DNSInterceptorService

            self.service = DNSInterceptorService("192.168.4.1")

    def _build_dns_query(
        self,
        transaction_id: int = 0x1234,
        flags: int = 0x0100,  # Standard query with recursion desired
        qdcount: int = 1,
        domain: str = "example.com",
        qtype: int = 1,  # A record
        qclass: int = 1,  # IN class
    ) -> bytes:
        """Build a DNS query packet for testing."""
        header = struct.pack(
            "!HHHHHH",
            transaction_id,
            flags,
            qdcount,
            0,  # ANCOUNT
            0,  # NSCOUNT
            0,  # ARCOUNT
        )
        question = self.service._encode_domain_name(domain)
        question += struct.pack("!HH", qtype, qclass)
        return header + question

    def test_parse_dns_query_valid_a_record(self) -> None:
        query = self._build_dns_query(transaction_id=0xABCD, domain="test.local")
        result = self.service._parse_dns_query(query)
        self.assertIsNotNone(result)
        assert result is not None
        transaction_id, domain, qtype, qclass = result
        self.assertEqual(transaction_id, 0xABCD)
        self.assertEqual(domain, "test.local")
        self.assertEqual(qtype, 1)  # A record
        self.assertEqual(qclass, 1)  # IN class

    def test_parse_dns_query_too_short(self) -> None:
        # Less than 12 bytes (minimum header size)
        result = self.service._parse_dns_query(b"\x00" * 11)
        self.assertIsNone(result)

    def test_parse_dns_query_multiple_questions(self) -> None:
        query = self._build_dns_query(qdcount=2)
        result = self.service._parse_dns_query(query)
        self.assertIsNone(result)

    def test_parse_dns_query_response_flag_set(self) -> None:
        # Response flag (0x8000) set - should reject
        query = self._build_dns_query(flags=0x8100)
        result = self.service._parse_dns_query(query)
        self.assertIsNone(result)


class TestDNSResponseCreation(unittest.TestCase):
    """Test DNS response packet creation."""

    def setUp(self) -> None:
        with patch("core.logging_helper.logger"):
            from services.dns_interceptor_service import DNSInterceptorService

            self.service = DNSInterceptorService("192.168.4.1")

    def test_create_a_record_response_structure(self) -> None:
        ip_bytes = bytes([192, 168, 4, 1])
        response = self.service._create_a_record_response(0x1234, "example.com", ip_bytes)
        self.assertIsNotNone(response)
        assert response is not None
        # Verify header
        header = struct.unpack("!HHHHHH", response[:12])
        self.assertEqual(header[0], 0x1234)  # Transaction ID
        self.assertEqual(header[2], 1)  # QDCOUNT = 1
        self.assertEqual(header[3], 1)  # ANCOUNT = 1
        # Verify IP in answer section (last 4 bytes)
        self.assertEqual(response[-4:], ip_bytes)

    def test_create_error_response_structure(self) -> None:
        response = self.service._create_error_response(0x5678, "bad.domain", 3)  # NXDOMAIN
        self.assertIsNotNone(response)
        assert response is not None
        header = struct.unpack("!HHHHHH", response[:12])
        self.assertEqual(header[0], 0x5678)  # Transaction ID
        self.assertEqual(header[2], 1)  # QDCOUNT = 1
        self.assertEqual(header[3], 0)  # ANCOUNT = 0 (error response)
        # Verify RCODE in flags
        flags = header[1]
        rcode = flags & 0x0F
        self.assertEqual(rcode, 3)  # NXDOMAIN


class TestDNSInterceptorLifecycle(unittest.TestCase):
    """Test DNS interceptor start/stop lifecycle."""

    def setUp(self) -> None:
        self.mock_socket = MagicMock()
        self.mock_socket_pool = MagicMock()
        self.mock_socket_pool.AF_INET = 2
        self.mock_socket_pool.SOCK_DGRAM = 2
        self.mock_socket_pool.socket.return_value = self.mock_socket

        with patch("core.logging_helper.logger"):
            from services.dns_interceptor_service import DNSInterceptorService

            self.service = DNSInterceptorService("192.168.4.1", socket_pool=self.mock_socket_pool)

    def test_start_without_socket_pool_returns_false(self) -> None:
        self.service.socket_pool = None
        result = self.service.start()
        self.assertFalse(result)
        self.assertFalse(self.service.running)

    def test_start_creates_and_binds_socket(self) -> None:
        result = self.service.start()
        self.assertTrue(result)
        self.assertTrue(self.service.running)
        self.mock_socket_pool.socket.assert_called_once_with(2, 2)
        self.mock_socket.setblocking.assert_called_once_with(False)
        self.mock_socket.bind.assert_called_once_with(("0.0.0.0", 53))

    def test_start_handles_oserror_address_in_use(self) -> None:
        error = OSError()
        error.errno = 98  # Address already in use (Linux)
        self.mock_socket_pool.socket.side_effect = error
        result = self.service.start()
        self.assertFalse(result)
        self.assertFalse(self.service.running)

    def test_start_handles_oserror_permission_denied(self) -> None:
        error = OSError()
        error.errno = 13  # Permission denied
        self.mock_socket_pool.socket.side_effect = error
        result = self.service.start()
        self.assertFalse(result)

    def test_stop_cleans_up_socket(self) -> None:
        self.service.start()
        self.service.stop()
        self.assertFalse(self.service.running)
        self.mock_socket.close.assert_called_once()
        self.assertIsNone(self.service.socket)
        self.assertIsNone(self.service.socket_pool)

    def test_stop_resets_error_counters(self) -> None:
        self.service.error_count = 5
        self.service.last_error_time = 12345.0
        self.service.stop()
        self.assertEqual(self.service.error_count, 0)
        self.assertEqual(self.service.last_error_time, 0)


class TestDNSInterceptorPolling(unittest.TestCase):
    """Test DNS query polling behavior."""

    def setUp(self) -> None:
        self.mock_socket = MagicMock()
        self.mock_socket_pool = MagicMock()
        self.mock_socket_pool.AF_INET = 2
        self.mock_socket_pool.SOCK_DGRAM = 2
        self.mock_socket_pool.socket.return_value = self.mock_socket

        with patch("core.logging_helper.logger"):
            from services.dns_interceptor_service import DNSInterceptorService

            self.service = DNSInterceptorService("192.168.4.1", socket_pool=self.mock_socket_pool)

    def test_poll_returns_zero_when_not_running(self) -> None:
        self.service.running = False
        result = self.service.poll()
        self.assertEqual(result, 0)

    def test_poll_returns_zero_when_no_socket(self) -> None:
        self.service.running = True
        self.service.socket = None
        result = self.service.poll()
        self.assertEqual(result, 0)

    def test_poll_handles_eagain(self) -> None:
        self.service.start()
        error = OSError()
        error.errno = 11  # EAGAIN
        self.mock_socket.recvfrom_into.side_effect = error
        result = self.service.poll()
        self.assertEqual(result, 0)

    def test_poll_handles_ewouldblock(self) -> None:
        self.service.start()
        error = OSError()
        error.errno = 35  # EWOULDBLOCK (macOS)
        self.mock_socket.recvfrom_into.side_effect = error
        result = self.service.poll()
        self.assertEqual(result, 0)


class TestDNSInterceptorHealth(unittest.TestCase):
    """Test health check functionality."""

    def setUp(self) -> None:
        with patch("core.logging_helper.logger"):
            from services.dns_interceptor_service import DNSInterceptorService

            self.service = DNSInterceptorService("192.168.4.1")

    def test_is_healthy_false_when_not_running(self) -> None:
        self.service.running = False
        self.assertFalse(self.service.is_healthy())

    def test_is_healthy_false_when_no_socket(self) -> None:
        self.service.running = True
        self.service.socket = None
        self.assertFalse(self.service.is_healthy())

    def test_is_healthy_true_when_running_with_socket(self) -> None:
        self.service.running = True
        self.service.socket = MagicMock()  # type: ignore[assignment]
        self.assertTrue(self.service.is_healthy())

    @patch("time.time", return_value=100.0)
    def test_is_healthy_false_during_backoff(self, mock_time: MagicMock) -> None:
        self.service.running = True
        self.service.socket = MagicMock()  # type: ignore[assignment]
        self.service.error_count = 10  # >= max_errors
        self.service.last_error_time = 99.5  # 0.5 seconds ago
        self.service.error_backoff = 1.0
        self.assertFalse(self.service.is_healthy())

    def test_get_status_returns_dict(self) -> None:
        self.service.running = True
        self.service.socket = MagicMock()  # type: ignore[assignment]
        status = self.service.get_status()
        self.assertIn("running", status)
        self.assertIn("healthy", status)
        self.assertIn("error_count", status)
        self.assertIn("in_backoff", status)


class TestDNSErrorHandling(unittest.TestCase):
    """Test error handling and backoff logic."""

    def setUp(self) -> None:
        with patch("core.logging_helper.logger"):
            from services.dns_interceptor_service import DNSInterceptorService

            self.service = DNSInterceptorService("192.168.4.1")

    @patch("time.time", return_value=1000.0)
    def test_handle_dns_error_increments_count(self, mock_time: MagicMock) -> None:
        self.service.error_count = 0
        self.service._handle_dns_error("test error")
        self.assertEqual(self.service.error_count, 1)
        self.assertEqual(self.service.last_error_time, 1000.0)

    @patch("time.time", return_value=1000.0)
    def test_handle_dns_error_exponential_backoff(self, mock_time: MagicMock) -> None:
        self.service.error_count = 9  # One below max
        self.service.error_backoff = 1.0
        self.service._handle_dns_error("test error")
        # After reaching max errors, backoff doubles
        self.assertEqual(self.service.error_backoff, 2.0)

    @patch("time.time", return_value=1000.0)
    def test_handle_dns_error_backoff_capped_at_30s(self, mock_time: MagicMock) -> None:
        self.service.error_count = 9
        self.service.error_backoff = 20.0
        self.service._handle_dns_error("test error")
        self.assertEqual(self.service.error_backoff, 30.0)  # Capped


if __name__ == "__main__":
    unittest.main()
