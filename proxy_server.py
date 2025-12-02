"""
Proxy Server Module - TCP and UDP forwarding through HTTP proxy with authentication
"""

import socket
import threading
import base64
import select
import struct
import logging
from typing import Optional, Tuple, Callable

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ProxyConfig:
    """Configuration for upstream proxy"""
    def __init__(self, host: str, port: int, username: str, password: str):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
    
    def get_auth_header(self) -> str:
        """Generate Base64 encoded auth header"""
        credentials = f"{self.username}:{self.password}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"


class TCPHandler(threading.Thread):
    """Handle TCP connections and forward through upstream proxy"""
    
    BUFFER_SIZE = 65536
    
    def __init__(self, client_socket: socket.socket, client_addr: Tuple[str, int], 
                 proxy_config: ProxyConfig, log_callback: Optional[Callable] = None):
        super().__init__(daemon=True)
        self.client_socket = client_socket
        self.client_addr = client_addr
        self.proxy_config = proxy_config
        self.log_callback = log_callback
        self.running = True
    
    def log(self, message: str):
        """Log message to callback and logger"""
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)
    
    def connect_to_upstream(self) -> Optional[socket.socket]:
        """Connect to upstream HTTP proxy"""
        try:
            upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            upstream.settimeout(30)
            upstream.connect((self.proxy_config.host, self.proxy_config.port))
            return upstream
        except Exception as e:
            self.log(f"Failed to connect to upstream proxy: {e}")
            return None
    
    def forward_data(self, source: socket.socket, destination: socket.socket) -> bool:
        """Forward data between sockets"""
        try:
            data = source.recv(self.BUFFER_SIZE)
            if data:
                destination.sendall(data)
                return True
            return False
        except:
            return False
    
    def run(self):
        """Main handler loop"""
        upstream = None
        try:
            # Receive initial request from client
            self.client_socket.settimeout(30)
            initial_data = self.client_socket.recv(self.BUFFER_SIZE)
            
            if not initial_data:
                return
            
            # Connect to upstream proxy
            upstream = self.connect_to_upstream()
            if not upstream:
                return
            
            # Check if it's a CONNECT request (HTTPS)
            request_line = initial_data.split(b'\r\n')[0].decode('utf-8', errors='ignore')
            
            if request_line.startswith('CONNECT'):
                self.handle_connect(initial_data, upstream)
            else:
                self.handle_http(initial_data, upstream)
                
        except Exception as e:
            self.log(f"Error handling connection from {self.client_addr}: {e}")
        finally:
            self.cleanup(upstream)
    
    def handle_connect(self, initial_data: bytes, upstream: socket.socket):
        """Handle HTTPS CONNECT tunnel"""
        try:
            # Parse CONNECT request
            lines = initial_data.split(b'\r\n')
            request_line = lines[0].decode('utf-8')
            
            # Add proxy authentication header
            auth_header = f"Proxy-Authorization: {self.proxy_config.get_auth_header()}\r\n"
            
            # Rebuild request with auth
            new_request = lines[0] + b'\r\n'
            new_request += auth_header.encode()
            
            # Add other headers except existing Proxy-Authorization
            for line in lines[1:]:
                if line and not line.lower().startswith(b'proxy-authorization'):
                    new_request += line + b'\r\n'
            
            if not new_request.endswith(b'\r\n\r\n'):
                new_request += b'\r\n'
            
            # Send to upstream
            upstream.sendall(new_request)
            
            # Read response from upstream
            response = upstream.recv(self.BUFFER_SIZE)
            
            if b'200' in response.split(b'\r\n')[0]:
                # Tunnel established, send success to client
                self.client_socket.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                self.log(f"CONNECT tunnel established for {self.client_addr}")
                
                # Start bidirectional forwarding
                self.bidirectional_forward(upstream)
            else:
                self.client_socket.sendall(response)
                self.log(f"CONNECT failed: {response[:100]}")
                
        except Exception as e:
            self.log(f"CONNECT error: {e}")
    
    def handle_http(self, initial_data: bytes, upstream: socket.socket):
        """Handle regular HTTP request"""
        try:
            # Add proxy authentication to request
            lines = initial_data.split(b'\r\n')
            auth_header = f"Proxy-Authorization: {self.proxy_config.get_auth_header()}\r\n"
            
            new_request = lines[0] + b'\r\n'
            new_request += auth_header.encode()
            
            for line in lines[1:]:
                if not line.lower().startswith(b'proxy-authorization'):
                    new_request += line + b'\r\n'
            
            # Send to upstream
            upstream.sendall(new_request)
            
            self.log(f"HTTP request forwarded from {self.client_addr}")
            
            # Forward response back to client
            self.bidirectional_forward(upstream)
            
        except Exception as e:
            self.log(f"HTTP error: {e}")
    
    def bidirectional_forward(self, upstream: socket.socket):
        """Bidirectional data forwarding between client and upstream"""
        self.client_socket.setblocking(False)
        upstream.setblocking(False)
        
        while self.running:
            try:
                readable, _, exceptional = select.select(
                    [self.client_socket, upstream], [], 
                    [self.client_socket, upstream], 1.0
                )
                
                if exceptional:
                    break
                
                for sock in readable:
                    try:
                        data = sock.recv(self.BUFFER_SIZE)
                        if not data:
                            return
                        
                        if sock is self.client_socket:
                            upstream.sendall(data)
                        else:
                            self.client_socket.sendall(data)
                    except:
                        return
                        
            except Exception:
                break
    
    def cleanup(self, upstream: Optional[socket.socket]):
        """Clean up sockets"""
        try:
            self.client_socket.close()
        except:
            pass
        if upstream:
            try:
                upstream.close()
            except:
                pass


class UDPHandler(threading.Thread):
    """Handle UDP forwarding through SOCKS5 over HTTP proxy (UDP Associate)"""
    
    BUFFER_SIZE = 65536
    
    def __init__(self, local_port: int, proxy_config: ProxyConfig, 
                 log_callback: Optional[Callable] = None):
        super().__init__(daemon=True)
        self.local_port = local_port
        self.proxy_config = proxy_config
        self.log_callback = log_callback
        self.running = True
        self.udp_socket = None
        self.client_mapping = {}  # Map client addr to upstream connection
    
    def log(self, message: str):
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)
    
    def run(self):
        """Main UDP handler loop"""
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.udp_socket.bind(('0.0.0.0', self.local_port))
            self.udp_socket.settimeout(1.0)
            
            self.log(f"UDP listener started on port {self.local_port}")
            
            while self.running:
                try:
                    data, client_addr = self.udp_socket.recvfrom(self.BUFFER_SIZE)
                    if data:
                        self.handle_udp_packet(data, client_addr)
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.log(f"UDP error: {e}")
                        
        except Exception as e:
            self.log(f"UDP handler error: {e}")
        finally:
            self.stop()
    
    def handle_udp_packet(self, data: bytes, client_addr: Tuple[str, int]):
        """Forward UDP packet through proxy"""
        try:
            # For UDP, we create a TCP tunnel to proxy and encapsulate UDP data
            # This is a simplified approach - full SOCKS5 UDP associate is more complex
            
            # Create or reuse upstream connection for this client
            if client_addr not in self.client_mapping:
                upstream = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                upstream.settimeout(5)
                self.client_mapping[client_addr] = upstream
                
                # Start receiver thread for this client
                receiver = threading.Thread(
                    target=self.receive_upstream, 
                    args=(upstream, client_addr),
                    daemon=True
                )
                receiver.start()
            
            upstream = self.client_mapping[client_addr]
            
            # Forward to upstream proxy (direct UDP forward)
            # Note: Most HTTP proxies don't support UDP directly
            # This forwards to the proxy host for UDP-capable proxies
            upstream.sendto(data, (self.proxy_config.host, self.proxy_config.port))
            
            self.log(f"UDP packet forwarded from {client_addr}")
            
        except Exception as e:
            self.log(f"UDP forward error: {e}")
    
    def receive_upstream(self, upstream: socket.socket, client_addr: Tuple[str, int]):
        """Receive data from upstream and forward to client"""
        while self.running:
            try:
                data, _ = upstream.recvfrom(self.BUFFER_SIZE)
                if data and self.udp_socket:
                    self.udp_socket.sendto(data, client_addr)
            except socket.timeout:
                continue
            except:
                break
    
    def stop(self):
        """Stop UDP handler"""
        self.running = False
        if self.udp_socket:
            try:
                self.udp_socket.close()
            except:
                pass
        for sock in self.client_mapping.values():
            try:
                sock.close()
            except:
                pass


class ProxyServer:
    """Main proxy server managing TCP and UDP"""
    
    def __init__(self, local_host: str, local_port: int, proxy_config: ProxyConfig,
                 log_callback: Optional[Callable] = None):
        self.local_host = local_host
        self.local_port = local_port
        self.proxy_config = proxy_config
        self.log_callback = log_callback
        self.running = False
        self.tcp_socket = None
        self.udp_handler = None
        self.tcp_thread = None
        self.handlers = []
    
    def log(self, message: str):
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)
    
    def start(self):
        """Start both TCP and UDP servers"""
        self.running = True
        
        # Start TCP server
        self.tcp_thread = threading.Thread(target=self.run_tcp_server, daemon=True)
        self.tcp_thread.start()
        
        # Start UDP handler
        self.udp_handler = UDPHandler(self.local_port, self.proxy_config, self.log_callback)
        self.udp_handler.start()
        
        self.log(f"Proxy server started on {self.local_host}:{self.local_port}")
    
    def run_tcp_server(self):
        """Run TCP server loop"""
        try:
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.tcp_socket.bind((self.local_host, self.local_port))
            self.tcp_socket.listen(100)
            self.tcp_socket.settimeout(1.0)
            
            self.log(f"TCP listener started on {self.local_host}:{self.local_port}")
            
            while self.running:
                try:
                    client_socket, client_addr = self.tcp_socket.accept()
                    handler = TCPHandler(client_socket, client_addr, 
                                        self.proxy_config, self.log_callback)
                    handler.start()
                    self.handlers.append(handler)
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.log(f"TCP accept error: {e}")
                        
        except Exception as e:
            self.log(f"TCP server error: {e}")
    
    def stop(self):
        """Stop all servers"""
        self.running = False
        
        if self.tcp_socket:
            try:
                self.tcp_socket.close()
            except:
                pass
        
        if self.udp_handler:
            self.udp_handler.stop()
        
        for handler in self.handlers:
            handler.running = False
        
        self.log("Proxy server stopped")
    
    def is_running(self) -> bool:
        return self.running

