"""Scan local network for camera with RTSP port 554 open."""
import socket

ips = [
    "192.168.1.2", "192.168.1.3", "192.168.1.4", "192.168.1.5",
    "192.168.1.6", "192.168.1.8", "192.168.1.9", "192.168.1.10",
    "192.168.1.17",
]

print("Scanning for RTSP (port 554) and HTTP (port 80) on local network...\n")

for ip in ips:
    for port, label in [(554, "RTSP"), (80, "HTTP"), (8080, "HTTP-ALT")]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        result = sock.connect_ex((ip, port))
        sock.close()
        if result == 0:
            print(f"  FOUND {label} on {ip}:{port}")

print("\nDone. Use the IP with RTSP port 554 open as your camera.")
