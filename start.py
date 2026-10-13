"""
ParseHub Combined Startup Script
Starts both frontend (Next.js) and optional backend (Python) services

Usage:
    python start.py
    python start.py --backend    # Include backend services
    python start.py --help       # Show help
"""

import os
import sys
import subprocess
import argparse
import platform
import time
import socket
from pathlib import Path
import threading


class ParseHubStarter:
    def __init__(self):
        self.root_dir = Path(__file__).parent
        self.frontend_dir = self.root_dir / "frontend"
        self.backend_dir = self.root_dir / "backend"
        self.venv_dir = self.root_dir / ".venv"
        self.platform = platform.system()
        self.backend_process = None
        self.backend_port = int(os.getenv("BACKEND_PORT", "5001"))
        self.frontend_port = int(os.getenv("FRONTEND_PORT", "3000"))
        self.python_exe = None

    def _is_port_in_use(self, port: int) -> bool:
        """Check whether a TCP port is already in use on localhost"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            return sock.connect_ex(("127.0.0.1", port)) == 0

    def _find_available_port(self, start_port: int) -> int:
        """Find the first available port starting from start_port"""
        port = start_port
        while self._is_port_in_use(port):
            port += 1
        return port

    def _resolve_python_executable(self):
        """Resolve Python executable: prefer .venv, fallback to current Python"""
        if self.platform == "Windows":
            venv_python = self.venv_dir / "Scripts" / "python.exe"
        else:
            venv_python = self.venv_dir / "bin" / "python"

        if venv_python.exists():
            self.python_exe = str(venv_python)
            print(f"✅ Using virtual environment Python: {self.python_exe}")
            return True

        self.python_exe = sys.executable
        print("⚠️  .venv not found, falling back to current Python executable")
        print(f"✅ Using Python: {self.python_exe}")
        return True

    def print_header(self):
        print("\n" + "="*60)
        print("    ParseHub - Frontend & Backend Startup")
        print("="*60 + "\n")

    def check_frontend(self):
        """Check frontend setup"""
        if not self.frontend_dir.exists():
            print("❌ Error: frontend directory not found!")
            return False

        print("📁 Frontend folder found at: frontend/")

        node_modules = self.frontend_dir / "node_modules"
        if not node_modules.exists():
            print("📦 Installing frontend dependencies...")
            cmd = ["npm", "install"] if self.platform != "Windows" else [
                "npm.cmd", "install"]
            result = subprocess.run(
                cmd,
                cwd=str(self.frontend_dir),
                capture_output=True,
                shell=self.platform == "Windows"
            )
            if result.returncode == 0:
                print("✅ Frontend dependencies installed\n")
            else:
                print("❌ Failed to install frontend dependencies")
                print(result.stderr.decode())
                return False
        else:
            print("✅ Frontend dependencies found\n")

        return True

    def check_backend(self):
        """Check backend setup"""
        if not self.backend_dir.exists():
            print("⚠️  Backend folder not found")
            return False

        print("📁 Backend folder found at: backend/")

        env_file = self.backend_dir / ".env"
        if env_file.exists():
            print("✅ Backend .env configuration found\n")
            self._resolve_python_executable()
            return True
        else:
            print("⚠️  backend/.env not found\n")
            self._resolve_python_executable()
            return True

    def start_backend(self):
        """Start the Flask backend development server"""
        print("🐍 Starting Backend Flask Server...")
        print(
            f"   Server will be available at: http://localhost:{self.backend_port}\n")

        try:
            backend_env = os.environ.copy()
            backend_env["BACKEND_PORT"] = str(self.backend_port)

            if self.platform == "Windows":
                # Start Flask API server in background
                self.backend_process = subprocess.Popen(
                    [self.python_exe, "api_server.py"],
                    cwd=str(self.backend_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=backend_env,
                    creationflags=subprocess.CREATE_NEW_CONSOLE
                )
                print("▶️  Flask server started in new console window")
                time.sleep(3)  # Give server more time to start

                # Check if process is still alive
                if self.backend_process.poll() is None:
                    print("✅ Backend server is running")
                    return True
                else:
                    print("❌ Backend server failed to start")
                    return False
            else:
                self.backend_process = subprocess.Popen(
                    [self.python_exe, "api_server.py"],
                    cwd=str(self.backend_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=backend_env
                )
                print("▶️  Flask server started in background")
                time.sleep(3)  # Give server more time to start

                # Check if process is still alive
                if self.backend_process.poll() is None:
                    print("✅ Backend server is running")
                    return True
                else:
                    print("❌ Backend server failed to start")
                    return False
        except Exception as e:
            print(f"❌ Error starting backend: {e}")
            return False

    def start_frontend(self):
        """Start the frontend development server"""
        print("🚀 Starting Frontend Development Server...")
        print(
            f"   Application will be available at: http://localhost:{self.frontend_port}\n")
        print(f"▶️  Running: npm run dev -- -p {self.frontend_port}\n")
        print("-" * 60 + "\n")

        try:
            frontend_env = os.environ.copy()
            frontend_env["PORT"] = str(self.frontend_port)

            if self.backend_process and self.backend_process.poll() is None:
                frontend_env["NEXT_PUBLIC_BACKEND_URL"] = f"http://localhost:{self.backend_port}"
                print(
                    f"🔗 Frontend backend URL: {frontend_env['NEXT_PUBLIC_BACKEND_URL']}")

            # Use different command for Windows
            if self.platform == "Windows":
                cmd = ["npm.cmd", "run", "dev", "--",
                       "-p", str(self.frontend_port)]
                subprocess.run(
                    cmd,
                    cwd=str(self.frontend_dir),
                    shell=True,
                    env=frontend_env
                )
            else:
                subprocess.run(
                    ["npm", "run", "dev", "--", "-p", str(self.frontend_port)],
                    cwd=str(self.frontend_dir),
                    env=frontend_env
                )
        except KeyboardInterrupt:
            print("\n\n✋ Shutting down ParseHub...")
            # Clean up backend process if running
            if self.backend_process:
                try:
                    if self.platform == "Windows":
                        os.system(
                            f"taskkill /F /PID {self.backend_process.pid}")
                    else:
                        self.backend_process.terminate()
                except:
                    pass
            sys.exit(0)
        except Exception as e:
            print(f"❌ Error starting frontend: {e}")
            sys.exit(1)

    def run(self, include_backend=False):
        """Run the startup sequence"""
        self.print_header()

        # Resolve available ports first to avoid collisions
        self.backend_port = self._find_available_port(self.backend_port)
        self.frontend_port = self._find_available_port(self.frontend_port)
        print(f"🔌 Selected backend port: {self.backend_port}")
        print(f"🔌 Selected frontend port: {self.frontend_port}\n")

        # Check frontend
        if not self.check_frontend():
            sys.exit(1)

        # Start backend (optional)
        if include_backend:
            if not self.check_backend():
                print("⚠️  Skipping backend startup")
            else:
                print("-" * 60 + "\n")
                if not self.start_backend():
                    print("⚠️  Backend failed to start, continuing with frontend only")
                else:
                    print("-" * 60 + "\n")

        # Start frontend (this blocks)
        self.start_frontend()


def main():
    parser = argparse.ArgumentParser(
        description="Start ParseHub Frontend & Backend services"
    )
    parser.add_argument(
        "--backend",
        action="store_true",
        help="Include backend services"
    )
    parser.add_argument(
        "--help-detailed",
        action="store_true",
        help="Show detailed help"
    )

    args = parser.parse_args()

    if args.help_detailed:
        print(__doc__)
        sys.exit(0)

    starter = ParseHubStarter()
    starter.run(include_backend=args.backend)


if __name__ == "__main__":
    main()
