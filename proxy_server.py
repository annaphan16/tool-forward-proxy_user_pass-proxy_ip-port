"""
Proxy Server Module - Using proxy.py library for robust HTTP proxy forwarding
Supports upstream proxy with authentication
"""

import subprocess
import threading
import signal
import sys
import os
import logging
from typing import Optional, Callable

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ProxyConfig:
    """Configuration for upstream proxy"""
    def __init__(self, host: str, port: int, username: str, password: str):
        self.host = host
        self.port = port
        self.username = username
        self.password = password

    def get_upstream_url(self) -> str:
        """Get upstream proxy URL with auth for proxy.py"""
        # Format: user:pass@host:port
        return f"{self.username}:{self.password}@{self.host}:{self.port}"


class ProxyServer:
    """
    Proxy server using proxy.py library
    Creates a local proxy that forwards to upstream proxy with authentication
    """

    def __init__(self, local_host: str, local_port: int, proxy_config: ProxyConfig,
                 log_callback: Optional[Callable] = None):
        self.local_host = local_host
        self.local_port = local_port
        self.proxy_config = proxy_config
        self.log_callback = log_callback
        self.running = False
        self.process: Optional[subprocess.Popen] = None
        self.log_thread: Optional[threading.Thread] = None

    def log(self, message: str):
        """Log message"""
        logger.info(message)
        if self.log_callback:
            self.log_callback(message)

    def start(self):
        """Start proxy.py with upstream proxy configuration"""
        self.running = True

        upstream_url = self.proxy_config.get_upstream_url()

        # Build command for proxy.py
        cmd = [
            sys.executable, "-m", "proxy",
            "--hostname", self.local_host,
            "--port", str(self.local_port),
            "--proxy-pool", upstream_url,
            "--timeout", "60",
            "--log-level", "WARNING"
        ]

        try:
            # Start proxy.py as subprocess
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            # Start log reader thread
            self.log_thread = threading.Thread(target=self._read_logs, daemon=True)
            self.log_thread.start()

            self.log(f"Proxy started on {self.local_host}:{self.local_port}")
            self.log(f"Upstream: {self.proxy_config.host}:{self.proxy_config.port}")

        except FileNotFoundError:
            self.log("Error: proxy.py not installed. Run: pip install proxy.py")
            self.running = False
            raise
        except Exception as e:
            self.log(f"Failed to start proxy: {e}")
            self.running = False
            raise

    def _read_logs(self):
        """Read and forward logs from proxy.py process"""
        if not self.process or not self.process.stdout:
            return

        try:
            for line in self.process.stdout:
                if not self.running:
                    break
                line = line.strip()
                if line:
                    self.log(f"[proxy.py] {line}")
        except:
            pass

    def stop(self):
        """Stop proxy server"""
        self.running = False

        if self.process:
            try:
                # Try graceful termination first
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    # Force kill if not responding
                    self.process.kill()
                    self.process.wait()
            except Exception as e:
                self.log(f"Error stopping proxy: {e}")
            finally:
                self.process = None

        self.log("Proxy server stopped")

    def is_running(self) -> bool:
        """Check if proxy is running"""
        if self.process:
            return self.process.poll() is None
        return False

