#!/usr/bin/env python3
"""
watcher.py -- Automated CRM Sync Watcher

Monitors a drop folder for incoming CSV files and automatically runs the
sync pipeline whenever a new file lands. Processed files are moved to an
archive folder with a timestamp so nothing is ever lost.

Usage:
    python3 watcher.py

Folder layout (created automatically on first run):
    watch/    -- Drop CSVs here. The watcher picks them up automatically.
    archive/  -- Processed files are moved here (renamed with a timestamp).

The watcher runs until you press Ctrl+C.

Requires: watchdog (pip3 install watchdog)
"""

import os
import sys
import time
import shutil
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR    = Path(__file__).parent.resolve()
WATCH_DIR   = BASE_DIR / "watch"
ARCHIVE_DIR = BASE_DIR / "archive"
SYNC_SCRIPT = BASE_DIR / "sync.py"
LOG_PATH    = BASE_DIR / "watcher_log.txt"

WATCH_DIR.mkdir(exist_ok=True)
ARCHIVE_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging():
    logger = logging.getLogger("crm_watcher")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ---------------------------------------------------------------------------
# Event handler
# ---------------------------------------------------------------------------

class CSVHandler(FileSystemEventHandler):
    """
    Fires when any file is created or moved into the watch folder.
    Only acts on .csv files. Waits briefly for the write to complete
    before processing.
    """

    def __init__(self, logger):
        super().__init__()
        self.logger = logger
        self._processing = set()

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(event.dest_path)

    def _handle(self, path):
        path = Path(path)

        if path.suffix.lower() != ".csv":
            self.logger.debug(f"Ignored (not a CSV): {path.name}")
            return

        if str(path) in self._processing:
            return
        self._processing.add(str(path))

        # Brief pause -- lets the file finish writing before we read it
        time.sleep(0.5)

        if not path.exists():
            self.logger.warning(f"File disappeared before processing: {path.name}")
            self._processing.discard(str(path))
            return

        self.logger.info(f"New file detected: {path.name}")
        self._run_sync(path)
        self._processing.discard(str(path))

    def _run_sync(self, csv_path):
        self.logger.info(f"Starting sync for: {csv_path.name}")

        result = subprocess.run(
            [sys.executable, str(SYNC_SCRIPT), str(csv_path)],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            self.logger.info(f"Sync completed successfully for: {csv_path.name}")
            self._archive(csv_path)
        else:
            self.logger.error(
                f"Sync failed for: {csv_path.name} "
                f"(exit code {result.returncode})"
            )
            if result.stderr:
                for line in result.stderr.strip().splitlines():
                    self.logger.error(f"  stderr: {line}")

    def _archive(self, csv_path):
        timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem       = csv_path.stem
        dest       = ARCHIVE_DIR / f"{stem}__{timestamp}.csv"
        shutil.move(str(csv_path), str(dest))
        self.logger.info(f"Archived to: archive/{dest.name}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    logger = setup_logging()

    logger.info("=" * 68)
    logger.info("CRM WATCHER STARTED")
    logger.info(f"Watching : {WATCH_DIR}")
    logger.info(f"Archive  : {ARCHIVE_DIR}")
    logger.info(f"Database : {BASE_DIR / 'crm.db'}")
    logger.info(f"Log      : {LOG_PATH}")
    logger.info("Drop a CSV file into the watch/ folder to trigger a sync.")
    logger.info("Press Ctrl+C to stop.")
    logger.info("=" * 68)

    handler  = CSVHandler(logger)
    observer = Observer()
    observer.schedule(handler, str(WATCH_DIR), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Watcher stopped by user.")
        observer.stop()

    observer.join()


if __name__ == "__main__":
    main()
