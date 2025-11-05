"""
DNS Interceptor for Captive Portal Setup

This module implements DNS query interception to redirect all domain name
resolution requests to the local setup portal IP address (192.168.4.1).
This is a key component of the captive portal functionality that ensures
users are automatically redirected to the setup interface when they
connect to the WICID access point.

The interceptor listens on UDP port 53 (standard DNS port) and responds
to all A record queries with the local IP address, effectively capturing
all DNS traffic and redirecting it to the setup portal.
"""

import struct
import time
from logging_helper import get_logger


class DNSInterceptor:
    """
    DNS query interceptor for captive portal functionality.
    
    Listens on UDP port 53 and responds to all DNS A record queries
    with the local setup portal IP address (192.168.4.1).
    
    Designed to fail gracefully if socket module is unavailable or
    if binding to port 53 fails (common on embedded systems).
    """
    
    # DNS constants
    DNS_PORT = 53
    DNS_QUERY_TYPE_A = 1      # A record (IPv4 address)
    DNS_QUERY_TYPE_AAAA = 28  # AAAA record (IPv6 address)
    DNS_CLASS_IN = 1          # Internet class
    
    # DNS response flags
    DNS_FLAG_RESPONSE = 0x8000     # Response flag
    DNS_FLAG_AUTHORITATIVE = 0x0400 # Authoritative answer
    DNS_FLAG_RECURSION_DESIRED = 0x0100  # Recursion desired (from query)
    
    # Response codes
    DNS_RCODE_NO_ERROR = 0    # No error
    DNS_RCODE_NAME_ERROR = 3  # Name does not exist
    
    def __init__(self, local_ip="192.168.4.1", socket_pool=None):
        """
        Initialize the DNS interceptor.
        
        Socket operates in non-blocking mode for smooth integration with
        main event loop and LED animation.
        
        Args:
            local_ip (str): IP address to return for all A record queries
            socket_pool: Optional socketpool.SocketPool instance (required for start())
        """
        self.local_ip = local_ip
        self.socket = None
        self.socket_pool = socket_pool
        self.running = False
        self.error_count = 0
        self.max_errors = 10  # Maximum consecutive errors before disabling
        self.last_error_time = 0
        self.error_backoff = 1.0  # Seconds to wait after errors
        self.logger = get_logger('wicid.dns')
        
        # Convert IP address to bytes for DNS response
        try:
            self.local_ip_bytes = self._ip_to_bytes(local_ip)
        except ValueError as e:
            self.logger.error(f"DNS Interceptor initialization failed: {e}")
            raise
    
    def _ip_to_bytes(self, ip_str):
        """
        Convert IP address string to 4-byte representation.
        
        Args:
            ip_str (str): IP address in dotted decimal notation
            
        Returns:
            bytes: 4-byte representation of IP address
        """
        try:
            parts = ip_str.split('.')
            if len(parts) != 4:
                raise ValueError("Invalid IP address format")
            
            return bytes([int(part) for part in parts])
        except ValueError as e:
            raise ValueError(f"Invalid IP address '{ip_str}': {e}")
    
    def start(self):
        """
        Start the DNS interceptor using CircuitPython's socketpool.
        
        Creates and binds a UDP socket to port 53 for DNS query interception.
        Uses the correct CircuitPython socket API.
        
        Returns:
            bool: True if started successfully, False otherwise
        """
        try:
            # Reset error counters on restart
            self.error_count = 0
            self.last_error_time = 0
            
            # Socket pool must be provided
            if not self.socket_pool:
                self.logger.warning("No socket pool provided")
                return False
            
            # Create UDP socket using CircuitPython API
            self.socket = self.socket_pool.socket(
                self.socket_pool.AF_INET,
                self.socket_pool.SOCK_DGRAM
            )
            
            # Set socket to non-blocking mode for polling
            # This ensures recvfrom_into() returns immediately if no data available
            self.socket.setblocking(False)
            
            # Note: settimeout() is not needed for non-blocking sockets
            # Non-blocking mode makes recvfrom_into() return immediately with EAGAIN
            # if no data is available, which is what we want for smooth LED animation
            
            # Bind to DNS port on all interfaces
            self.socket.bind(('0.0.0.0', self.DNS_PORT))
            
            self.running = True
            
            self.logger.info(f"DNS interceptor started successfully on port {self.DNS_PORT}")
            
            return True
            
        except OSError as e:
            error_msg = f"Failed to start DNS interceptor (OSError): {e}"
            
            # Check for common error codes
            errno = getattr(e, 'errno', None)
            if errno == 98 or errno == 48:  # Address already in use (Linux/macOS)
                error_msg += " - Port 53 already in use"
            elif errno == 13 or errno == 1:  # Permission denied
                error_msg += " - Permission denied for port 53"
            elif errno:
                error_msg += f" (errno: {errno})"
            
            self.logger.warning(error_msg)
            self.logger.info("Captive portal will use HTTP-only detection")
            self._cleanup_socket()
            return False
            
        except AttributeError as e:
            self.logger.warning(f"DNS interceptor failed: socketpool API not available: {e}")
            self.logger.info("Captive portal will use HTTP-only detection")
            self._cleanup_socket()
            return False
            
        except Exception as e:
            self.logger.error(f"Unexpected error starting DNS interceptor: {e}")
            self.logger.info("Captive portal will use HTTP-only detection")
            self._cleanup_socket()
            return False
    
    def stop(self):
        """
        Stop the DNS interceptor and clean up resources with error handling.
        """
        try:
            self.running = False
            self._cleanup_socket()
            
            # Reset error counters
            self.error_count = 0
            self.last_error_time = 0
            
            self.logger.debug("DNS interceptor stopped successfully")
                
        except Exception as e:
            self.logger.warning(f"Error stopping DNS interceptor: {e}")
            # Force cleanup even if there are errors
            try:
                self._cleanup_socket()
            except:
                pass
    
    def _cleanup_socket(self):
        """
        Clean up socket resources safely.
        """
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            finally:
                self.socket = None
        
        # Clear socket pool reference
        self.socket_pool = None
    
    def poll(self):
        """
        Poll for incoming DNS queries with comprehensive error handling.
        
        This method should be called regularly in the main loop to process
        incoming DNS queries. It's non-blocking and returns immediately
        if no queries are pending. Implements error backoff and graceful degradation.
        
        Returns:
            int: Number of queries processed (0 if none or if disabled due to errors)
        """
        if not self.running or not self.socket:
            return 0
        
        # Check if we're in error backoff period
        current_time = time.time()
        if self.error_count >= self.max_errors:
            if current_time - self.last_error_time < self.error_backoff:
                return 0  # Still in backoff period
            else:
                # Reset error count after backoff period
                self.error_count = 0
        
        queries_processed = 0
        
        try:
            # Process up to 10 queries per poll to avoid blocking too long
            for _ in range(10):
                try:
                    # Receive DNS query (non-blocking)
                    buffer = bytearray(512)  # DNS packets are typically < 512 bytes
                    nbytes, client_addr = self.socket.recvfrom_into(buffer)
                    data = bytes(buffer[:nbytes])
                    
                    # Handle the query with timeout protection
                    self._handle_dns_query_with_timeout(data, client_addr)
                    queries_processed += 1
                    
                    # Reset error count on successful processing
                    if self.error_count > 0:
                        self.error_count = 0
                    
                except OSError as e:
                    # No more data available - this is normal for non-blocking sockets
                    errno = getattr(e, 'errno', None)
                    if errno in (11, 35, 116):  # EAGAIN, EWOULDBLOCK, or ETIMEDOUT
                        break
                    else:
                        self._handle_dns_error(f"Socket error: {e}")
                        break
                except Exception as e:
                    self._handle_dns_error(f"Error processing query: {e}")
                    continue
                    
        except Exception as e:
            self._handle_dns_error(f"Critical error in DNS poll: {e}")
        
        return queries_processed
    
    def _handle_dns_error(self, error_msg):
        """
        Handle DNS operation errors with backoff and logging.
        
        Args:
            error_msg (str): Error message to log
        """
        self.error_count += 1
        self.last_error_time = time.time()
        
        if self.error_count >= self.max_errors:
            self.logger.warning("DNS interceptor disabled due to errors")
            self.logger.info("Captive portal will continue with HTTP-only detection")
            # Don't stop completely, just enter backoff mode
            self.error_backoff = min(self.error_backoff * 2, 30.0)  # Exponential backoff, max 30s
    
    def _handle_dns_query_with_timeout(self, query_data, client_addr):
        """
        Handle a DNS query with timeout protection.
        
        Args:
            query_data (bytes): Raw DNS query packet
            client_addr (tuple): Client address (ip, port)
        """
        try:
            # Set a processing timeout to prevent hanging
            start_time = time.time()
            
            # Handle the query
            self._handle_dns_query(query_data, client_addr)
            
            # Check if processing took too long
            processing_time = time.time() - start_time
            if processing_time > 1.0:  # Warn if processing takes more than 1 second
                self.logger.warning(f"DNS query processing took {processing_time:.2f}s")
                
        except Exception as e:
            raise Exception(f"DNS query processing failed: {e}")
    
    def _handle_dns_query(self, query_data, client_addr):
        """
        Handle a DNS query and send appropriate response with error handling.
        
        Args:
            query_data (bytes): Raw DNS query packet
            client_addr (tuple): Client address (ip, port)
        """
        response = None
        
        try:
            # Validate input data
            if not query_data or len(query_data) < 12:
                return
            
            # Parse the DNS query
            parsed_query = self._parse_dns_query(query_data)
            
            if not parsed_query:
                return
            
            transaction_id, domain, query_type, query_class = parsed_query
            
            # Generate response based on query type
            if query_type == self.DNS_QUERY_TYPE_A and query_class == self.DNS_CLASS_IN:
                # A record query - respond with local IP
                response = self._create_a_record_response(
                    transaction_id, domain, self.local_ip_bytes
                )
                    
            elif query_type == self.DNS_QUERY_TYPE_AAAA:
                # AAAA record query (IPv6) - respond with name error
                response = self._create_error_response(
                    transaction_id, domain, self.DNS_RCODE_NAME_ERROR
                )
                    
            else:
                # Other query types - respond with name error
                response = self._create_error_response(
                    transaction_id, domain, self.DNS_RCODE_NAME_ERROR
                )
            
            # Send response with error handling
            if response:
                try:
                    self.socket.sendto(response, client_addr)
                except OSError:
                    pass  # Continue processing other queries
                
        except Exception:
            # Try to send a generic error response if we have the transaction ID
            if response is None:
                try:
                    if len(query_data) >= 2:
                        transaction_id = (query_data[0] << 8) | query_data[1]
                        error_response = self._create_error_response(
                            transaction_id, "", self.DNS_RCODE_NAME_ERROR
                        )
                        if error_response:
                            self.socket.sendto(error_response, client_addr)
                except:
                    pass
    
    def _parse_dns_query(self, data):
        """
        Parse a DNS query packet to extract key information.
        
        Args:
            data (bytes): Raw DNS query packet
            
        Returns:
            tuple: (transaction_id, domain, query_type, query_class) or None if parsing fails
        """
        try:
            if len(data) < 12:  # Minimum DNS header size
                return None
            
            # Parse DNS header (first 12 bytes)
            header = struct.unpack('!HHHHHH', data[:12])
            transaction_id = header[0]
            flags = header[1]
            qdcount = header[2]  # Number of questions
            
            # We only handle queries with exactly one question
            if qdcount != 1:
                return None
            
            # Check if this is a query (not a response)
            if flags & self.DNS_FLAG_RESPONSE:
                return None
            
            # Parse the question section (starts at byte 12)
            offset = 12
            domain, offset = self._parse_domain_name(data, offset)
            
            if offset + 4 > len(data):
                return None
            
            # Parse QTYPE and QCLASS (2 bytes each)
            qtype, qclass = struct.unpack('!HH', data[offset:offset+4])
            
            return transaction_id, domain, qtype, qclass
            
        except:
            return None
    
    def _parse_domain_name(self, data, offset):
        """
        Parse a domain name from DNS packet data.
        
        Args:
            data (bytes): DNS packet data
            offset (int): Starting offset in the data
            
        Returns:
            tuple: (domain_name, new_offset) or raises exception on error
        """
        domain_parts = []
        
        while offset < len(data):
            length = data[offset]
            offset += 1
            
            if length == 0:
                break
            elif length & 0xC0:
                # Compression pointer - skip and end parsing
                offset += 1
                break
            else:
                if offset + length > len(data):
                    raise ValueError("Invalid domain name length")
                
                try:
                    label = data[offset:offset+length].decode('ascii')
                except:
                    label = ''
                domain_parts.append(label)
                offset += length
        
        domain = '.'.join(domain_parts) if domain_parts else ''
        return domain, offset
    
    def _create_a_record_response(self, transaction_id, domain, ip_bytes):
        """
        Create a DNS A record response.
        
        Args:
            transaction_id (int): Transaction ID from the query
            domain (str): Domain name being queried
            ip_bytes (bytes): 4-byte IP address to return
            
        Returns:
            bytes: DNS response packet
        """
        try:
            # DNS Header (12 bytes)
            flags = (self.DNS_FLAG_RESPONSE | 
                    self.DNS_FLAG_AUTHORITATIVE | 
                    self.DNS_FLAG_RECURSION_DESIRED)
            
            header = struct.pack('!HHHHHH',
                transaction_id,
                flags,
                1,  # QDCOUNT (1 question)
                1,  # ANCOUNT (1 answer)
                0,  # NSCOUNT
                0   # ARCOUNT
            )
            
            # Question section
            question = self._encode_domain_name(domain)
            question += struct.pack('!HH', 
                self.DNS_QUERY_TYPE_A,
                self.DNS_CLASS_IN
            )
            
            # Answer section with compression pointer
            answer = b'\xc0\x0c'  # Compression pointer to offset 12
            answer += struct.pack('!HHIH',
                self.DNS_QUERY_TYPE_A,
                self.DNS_CLASS_IN,
                300,  # TTL (5 minutes)
                4     # RDLENGTH
            )
            answer += ip_bytes
            
            return header + question + answer
            
        except:
            return None
    
    def _create_error_response(self, transaction_id, domain, rcode):
        """
        Create a DNS error response.
        
        Args:
            transaction_id (int): Transaction ID from the query
            domain (str): Domain name being queried
            rcode (int): Response code (error type)
            
        Returns:
            bytes: DNS response packet
        """
        try:
            # DNS Header with error code
            flags = (self.DNS_FLAG_RESPONSE | 
                    self.DNS_FLAG_RECURSION_DESIRED | 
                    (rcode & 0x0F))  # Mask to ensure only bits 0-3 are used
            
            header = struct.pack('!HHHHHH',
                transaction_id,
                flags,
                1,  # QDCOUNT (1 question)
                0,  # ANCOUNT (0 answers)
                0,  # NSCOUNT
                0   # ARCOUNT
            )
            
            # Question section
            question = self._encode_domain_name(domain)
            question += struct.pack('!HH', 
                self.DNS_QUERY_TYPE_A,
                self.DNS_CLASS_IN
            )
            
            return header + question
            
        except:
            return None
    
    def _encode_domain_name(self, domain):
        """
        Encode a domain name for DNS packet format.
        
        Args:
            domain (str): Domain name to encode
            
        Returns:
            bytes: Encoded domain name
        """
        if not domain:
            return b'\x00'
        
        encoded = b''
        for part in domain.split('.'):
            if len(part) > 63:
                part = part[:63]
            
            try:
                part_bytes = part.encode('ascii')
            except:
                part_bytes = b''
            encoded += bytes([len(part_bytes)]) + part_bytes
        
        encoded += b'\x00'
        return encoded
    
    def is_healthy(self):
        """
        Check if the DNS interceptor is healthy and operational.
        
        Returns:
            bool: True if healthy, False if disabled due to errors
        """
        if not self.running or not self.socket:
            return False
        
        # Check if we're in error backoff mode
        if self.error_count >= self.max_errors:
            current_time = time.time()
            if current_time - self.last_error_time < self.error_backoff:
                return False  # Still in backoff period
        
        return True
    
    def get_status(self):
        """
        Get basic status information about the DNS interceptor.
        
        Returns:
            dict: Status information including health and error count
        """
        status = {
            'running': self.running,
            'healthy': self.is_healthy(),
            'error_count': self.error_count,
            'in_backoff': False
        }
        
        # Check backoff status
        if self.error_count >= self.max_errors:
            current_time = time.time()
            backoff_remaining = self.error_backoff - (current_time - self.last_error_time)
            if backoff_remaining > 0:
                status['in_backoff'] = True
        
        return status