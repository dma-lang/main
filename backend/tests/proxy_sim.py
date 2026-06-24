"""A local stand-in for the Cloud SQL Auth Proxy, for end-to-end failure simulation.

Cloud Run reaches Cloud SQL through a proxy that exposes a unix socket at
``<dir>/.s.PGSQL.5432``. Every production failure we saw lives in that hop, so this fake proxy
reproduces each one against a REAL local Postgres:

  mode="drop"         accept the client, then close immediately — what the real proxy does when
                      it cannot reach the instance backend (private-IP-only, no route) or has not
                      finished its tunnel: the client sees
                      "server closed the connection unexpectedly".
  mode="drop_then_ok" drop for ``drop_for`` seconds, then forward bytes to the real Postgres —
                      the startup race: the sidecar comes up after the app container.
  (no proxy at all)   the socket file is absent — the sidecar has not even created it yet.

Used by tests/test_migrate.py to prove the migration runner self-heals the transient shapes and
stays bounded on the permanent one.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path


def _pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class FakeSqlProxy(threading.Thread):
    """Unix-socket front for a TCP Postgres, with scriptable misbehaviour."""

    def __init__(
        self,
        sockdir: str | Path,
        target_host: str = "127.0.0.1",
        target_port: int = 5432,
        mode: str = "drop_then_ok",
        drop_for: float = 3.0,
    ) -> None:
        super().__init__(daemon=True)
        self.path = Path(sockdir) / ".s.PGSQL.5432"
        self.target = (target_host, target_port)
        self.mode = mode
        self.deadline = time.monotonic() + drop_for
        self.dropped = 0
        self.forwarded = 0
        self._stop = threading.Event()
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(self.path))
        self._server.listen(8)
        self._server.settimeout(0.2)

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            dropping = self.mode == "drop" or (
                self.mode == "drop_then_ok" and time.monotonic() < self.deadline
            )
            if dropping:
                self.dropped += 1
                conn.close()  # accept-then-drop: the production signature
                continue
            try:
                upstream = socket.create_connection(self.target, timeout=5)
            except OSError:
                self.dropped += 1
                conn.close()
                continue
            self.forwarded += 1
            threading.Thread(target=_pump, args=(conn, upstream), daemon=True).start()
            threading.Thread(target=_pump, args=(upstream, conn), daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._server.close()
        except OSError:
            pass
        self.path.unlink(missing_ok=True)
