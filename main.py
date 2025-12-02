"""
Proxy Swap Tool - GUI Application
Convert HTTP proxy with authentication to local proxy without auth
Supports multiple proxies at once
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import re
from typing import Optional, List, Dict
from proxy_server import ProxyServer, ProxyConfig


class ProxySwapApp:
    """Main GUI Application for Proxy Swap Tool"""

    DEFAULT_LOCAL_PORT = 30000

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Proxy Swap Tool - Multi Proxy Support")
        self.root.geometry("800x700")
        self.root.resizable(True, True)

        self.proxy_servers: List[ProxyServer] = []
        self.proxy_mappings: List[Dict] = []  # Store mapping info
        self.start_port = self.DEFAULT_LOCAL_PORT

        self.setup_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_ui(self):
        """Setup the user interface"""
        # Main frame with padding
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        # Title
        title_label = ttk.Label(main_frame, text="Proxy Swap Tool - Multi Proxy",
                                font=("Helvetica", 16, "bold"))
        title_label.grid(row=0, column=0, pady=(0, 15))

        # Input frame
        input_frame = ttk.LabelFrame(main_frame, text="Upstream Proxy Configuration (one per line: ip:port:user:pass)",
                                     padding="10")
        input_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        # Proxy input - Text area for multiple proxies
        self.proxy_text = scrolledtext.ScrolledText(input_frame, height=8, wrap=tk.NONE)
        self.proxy_text.grid(row=0, column=0, sticky="nsew")

        # Port frame
        port_frame = ttk.Frame(input_frame)
        port_frame.grid(row=1, column=0, sticky="w", pady=(10, 0))

        ttk.Label(port_frame, text="Starting Local Port:").grid(row=0, column=0, sticky="w")
        self.port_entry = ttk.Entry(port_frame, width=10)
        self.port_entry.grid(row=0, column=1, padx=(10, 0))
        self.port_entry.insert(0, str(self.DEFAULT_LOCAL_PORT))

        ttk.Label(port_frame, text="(ports will auto-increment: 30000, 30001, 30002...)",
                  foreground="gray").grid(row=0, column=2, padx=(10, 0))

        # Buttons frame
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=2, column=0, pady=10)

        self.start_button = ttk.Button(button_frame, text="Start All Proxies",
                                        command=self.start_proxies)
        self.start_button.grid(row=0, column=0, padx=5)

        self.stop_button = ttk.Button(button_frame, text="Stop All Proxies",
                                       command=self.stop_proxies, state="disabled")
        self.stop_button.grid(row=0, column=1, padx=5)

        self.clear_button = ttk.Button(button_frame, text="Clear Log",
                                        command=self.clear_log)
        self.clear_button.grid(row=0, column=2, padx=5)

        # Mapping frame - show all proxy mappings
        mapping_frame = ttk.LabelFrame(main_frame, text="Proxy Mappings (Local → Upstream)", padding="10")
        mapping_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 10))
        mapping_frame.columnconfigure(0, weight=1)
        mapping_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)

        # Treeview for mappings
        columns = ("local", "upstream", "status")
        self.mapping_tree = ttk.Treeview(mapping_frame, columns=columns, show="headings", height=6)
        self.mapping_tree.heading("local", text="Local Proxy")
        self.mapping_tree.heading("upstream", text="Upstream Proxy")
        self.mapping_tree.heading("status", text="Status")
        self.mapping_tree.column("local", width=150)
        self.mapping_tree.column("upstream", width=300)
        self.mapping_tree.column("status", width=100)

        scrollbar = ttk.Scrollbar(mapping_frame, orient="vertical", command=self.mapping_tree.yview)
        self.mapping_tree.configure(yscrollcommand=scrollbar.set)

        self.mapping_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Copy buttons frame
        copy_frame = ttk.Frame(mapping_frame)
        copy_frame.grid(row=1, column=0, columnspan=2, pady=(10, 0))

        self.copy_all_button = ttk.Button(copy_frame, text="Copy All Local Proxies",
                                           command=self.copy_all_proxies, state="disabled")
        self.copy_all_button.grid(row=0, column=0, padx=5)

        self.copy_selected_button = ttk.Button(copy_frame, text="Copy Selected",
                                                command=self.copy_selected_proxy, state="disabled")
        self.copy_selected_button.grid(row=0, column=1, padx=5)

        # Status label
        self.status_label = ttk.Label(mapping_frame, text="Status: Stopped (0 proxies)",
                                       foreground="red", font=("Helvetica", 10, "bold"))
        self.status_label.grid(row=2, column=0, columnspan=2, pady=(10, 0))

        # Log frame
        log_frame = ttk.LabelFrame(main_frame, text="Activity Log", padding="10")
        log_frame.grid(row=4, column=0, sticky="nsew", pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=8,
                                                   state="disabled", wrap=tk.WORD)
        self.log_text.grid(row=0, column=0, sticky="nsew")

        # Info label
        info_label = ttk.Label(main_frame,
                               text="Supports TCP and UDP forwarding through HTTP proxy | Enter multiple proxies, one per line",
                               font=("Helvetica", 9), foreground="gray")
        info_label.grid(row=5, column=0)
    
    def log(self, message: str):
        """Add message to log (thread-safe)"""
        def update():
            self.log_text.config(state="normal")
            self.log_text.insert(tk.END, f"{message}\n")
            self.log_text.see(tk.END)
            self.log_text.config(state="disabled")
        
        self.root.after(0, update)
    
    def clear_log(self):
        """Clear the log"""
        self.log_text.config(state="normal")
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state="disabled")
    
    def parse_proxy_line(self, proxy_str: str, show_error: bool = True) -> Optional[ProxyConfig]:
        """Parse proxy string in format ip:port:user:pass"""
        proxy_str = proxy_str.strip()

        if not proxy_str:
            return None

        # Skip comments and empty lines
        if proxy_str.startswith('#'):
            return None

        # Try to parse ip:port:user:pass format
        parts = proxy_str.split(':')

        if len(parts) == 4:
            host, port_str, username, password = parts
        elif len(parts) > 4:
            # Handle case where password contains ':'
            host = parts[0]
            port_str = parts[1]
            username = parts[2]
            password = ':'.join(parts[3:])
        else:
            if show_error:
                self.log(f"Invalid format: {proxy_str}")
            return None

        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                raise ValueError("Port out of range")
        except ValueError:
            if show_error:
                self.log(f"Invalid port in: {proxy_str}")
            return None

        # Validate IP/hostname
        if not host:
            if show_error:
                self.log(f"Invalid host in: {proxy_str}")
            return None

        return ProxyConfig(host, port, username, password)

    def start_proxies(self):
        """Start all proxy servers"""
        # Get all proxy lines
        proxy_text = self.proxy_text.get("1.0", tk.END)
        proxy_lines = [line.strip() for line in proxy_text.split('\n') if line.strip() and not line.strip().startswith('#')]

        if not proxy_lines:
            messagebox.showerror("Error", "Please enter at least one proxy")
            return

        # Get starting port
        try:
            self.start_port = int(self.port_entry.get())
            if not (1024 <= self.start_port <= 65535):
                raise ValueError("Port must be between 1024 and 65535")
        except ValueError as e:
            messagebox.showerror("Error", f"Invalid starting port: {e}")
            return

        # Check if we have enough ports
        if self.start_port + len(proxy_lines) > 65535:
            messagebox.showerror("Error", "Not enough ports available for all proxies")
            return

        # Clear previous mappings
        self.proxy_servers = []
        self.proxy_mappings = []
        for item in self.mapping_tree.get_children():
            self.mapping_tree.delete(item)

        # Parse and start each proxy
        current_port = self.start_port
        success_count = 0

        for proxy_line in proxy_lines:
            proxy_config = self.parse_proxy_line(proxy_line)
            if not proxy_config:
                continue

            try:
                server = ProxyServer(
                    "127.0.0.1",
                    current_port,
                    proxy_config,
                    log_callback=self.log
                )
                server.start()

                # Store mapping
                mapping = {
                    "local": f"127.0.0.1:{current_port}",
                    "upstream": f"{proxy_config.host}:{proxy_config.port}",
                    "upstream_full": proxy_line,
                    "status": "Running"
                }
                self.proxy_servers.append(server)
                self.proxy_mappings.append(mapping)

                # Add to treeview
                self.mapping_tree.insert("", "end", values=(
                    mapping["local"],
                    mapping["upstream"],
                    mapping["status"]
                ))

                self.log(f"Started: 127.0.0.1:{current_port} → {proxy_config.host}:{proxy_config.port}")

                current_port += 1
                success_count += 1

            except Exception as e:
                self.log(f"Failed to start proxy on port {current_port}: {e}")
                current_port += 1

        if success_count > 0:
            # Update UI
            self.status_label.config(
                text=f"Status: Running ({success_count} proxies)",
                foreground="green"
            )
            self.start_button.config(state="disabled")
            self.stop_button.config(state="normal")
            self.copy_all_button.config(state="normal")
            self.copy_selected_button.config(state="normal")
            self.proxy_text.config(state="disabled")
            self.port_entry.config(state="disabled")

            self.log(f"Successfully started {success_count} proxy servers")
        else:
            messagebox.showerror("Error", "Failed to start any proxy servers")

    def stop_proxies(self):
        """Stop all proxy servers"""
        for server in self.proxy_servers:
            try:
                server.stop()
            except:
                pass

        self.proxy_servers = []
        self.proxy_mappings = []

        # Clear treeview
        for item in self.mapping_tree.get_children():
            self.mapping_tree.delete(item)

        # Update UI
        self.status_label.config(text="Status: Stopped (0 proxies)", foreground="red")
        self.start_button.config(state="normal")
        self.stop_button.config(state="disabled")
        self.copy_all_button.config(state="disabled")
        self.copy_selected_button.config(state="disabled")
        self.proxy_text.config(state="normal")
        self.port_entry.config(state="normal")

        self.log("All proxy servers stopped")

    def copy_all_proxies(self):
        """Copy all local proxy addresses to clipboard"""
        if not self.proxy_mappings:
            return

        proxy_list = "\n".join([m["local"] for m in self.proxy_mappings])
        self.root.clipboard_clear()
        self.root.clipboard_append(proxy_list)
        self.log(f"Copied {len(self.proxy_mappings)} local proxies to clipboard")

    def copy_selected_proxy(self):
        """Copy selected local proxy address to clipboard"""
        selection = self.mapping_tree.selection()
        if not selection:
            messagebox.showinfo("Info", "Please select a proxy from the list")
            return

        item = self.mapping_tree.item(selection[0])
        local_proxy = item["values"][0]
        self.root.clipboard_clear()
        self.root.clipboard_append(local_proxy)
        self.log(f"Copied to clipboard: {local_proxy}")
    
    def on_closing(self):
        """Handle window close"""
        self.stop_proxies()
        self.root.destroy()


def main():
    """Main entry point"""
    root = tk.Tk()
    app = ProxySwapApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
