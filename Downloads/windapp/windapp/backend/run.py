"""Start the API.  Local default: http://127.0.0.1:8000 (IPv4 only, matches the Vite proxy).
Docker sets HOST=0.0.0.0.  Usage: python run.py   (from backend/)"""
import os
import socket
import sys

import uvicorn

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

if __name__ == "__main__":
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            sys.exit(f"Port {PORT} is already in use. Stop the other process or set PORT=<free port> "
                     f"(and update the proxy target in frontend/vite.config.js).")
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=bool(os.environ.get("RELOAD")))
