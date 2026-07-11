#!/usr/bin/env python3
"""Dev server for LobbyistIQ previews.

Serves the repo root with the directory pinned explicitly (the Claude
Preview sandbox can't resolve os.getcwd(), so plain `python3 -m
http.server` fails there). Port comes from $PORT when set.
"""

import functools
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("PORT", "8749"))

handler = functools.partial(SimpleHTTPRequestHandler, directory=str(ROOT))
print(f"Serving {ROOT} on http://127.0.0.1:{PORT}")
ThreadingHTTPServer(("127.0.0.1", PORT), handler).serve_forever()
