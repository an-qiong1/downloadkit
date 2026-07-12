"""One-click launcher for downloadkit web UI.

Starts the FastAPI server and opens the browser automatically.
Optimized for faster startup and better error handling.
"""

import sys
import time
import webbrowser
import socket
import subprocess
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"


def check_port(port: int) -> bool:
    """Check if a port is already in use."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    result = sock.connect_ex((HOST, port))
    sock.close()
    return result == 0


def find_available_port(start_port: int = 8765, max_port: int = 8800) -> int:
    """Find an available port starting from start_port."""
    for port in range(start_port, max_port + 1):
        if not check_port(port):
            return port
    raise RuntimeError(f"No available port found between {start_port} and {max_port}")


def main():
    global PORT, URL
    
    # Check if default port is available
    if check_port(PORT):
        print(f"Port {PORT} is in use, finding available port...")
        PORT = find_available_port()
        URL = f"http://{HOST}:{PORT}"
        print(f"Using port {PORT}")
    
    project_dir = Path(__file__).parent
    sys.path.insert(0, str(project_dir))
    
    print(f"Starting downloadkit server at {URL} ...")
    
    # Start uvicorn directly (faster and more reliable)
    proc = subprocess.Popen([
        sys.executable, "-m", "uvicorn", 
        "server:app", 
        "--host", HOST, 
        "--port", str(PORT), 
        "--log-level", "warning"
    ], cwd=str(project_dir))
    
    # Wait for server to be ready
    print("Waiting for server...", end="", flush=True)
    for _ in range(30):
        time.sleep(0.3)
        if check_port(PORT):
            print("\r", end="")
            break
        print(".", end="", flush=True)
    else:
        print("\nWarning: server may not be ready")
    
    # Open browser
    print(f"Opening {URL} ...")
    webbrowser.open(URL)
    
    print("Press Ctrl+C to stop the server.")
    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    main()
