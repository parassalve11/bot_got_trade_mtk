import os
from pathlib import Path


class WorkerLock:
    """Process-held OS lock; no lease can expire while a broker call is blocked."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        # Reading the byte itself fails on Windows when another process owns its lock.
        # Inspect file length instead; never touch a region locked by another worker.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise RuntimeError("Another worker owns this database") from None
        self.handle = handle
        return self

    def __exit__(self, *_):
        if self.handle:
            self.handle.close()  # OS also releases the lock on crash/process termination.
            self.handle = None
