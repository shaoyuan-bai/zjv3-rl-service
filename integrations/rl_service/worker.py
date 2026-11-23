"""Terminate only our simulation process tree on cancellation or API death."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil


def stop_tree(pid):
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for p in reversed(children):
            try:
                p.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.terminate()
        _, alive = psutil.wait_procs(children + [parent], timeout=8)
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('job', type=Path)
    args = parser.parse_args()
    job = json.loads(args.job.read_text(encoding='utf-8'))
    proc = subprocess.Popen(job['command'], cwd=job['cwd'], env={**os.environ, **job['env']}, stdin=subprocess.DEVNULL)
    try:
        while proc.poll() is None:
            try:
                owner = psutil.Process(job['owner_pid'])
                live = owner.create_time() == job['owner_start'] and owner.is_running()
            except psutil.NoSuchProcess:
                live = False
            if not live or Path(job['cancel_file']).exists():
                stop_tree(proc.pid)
                return 130
            time.sleep(.25)
        return proc.returncode
    finally:
        if proc.poll() is None:
            stop_tree(proc.pid)


if __name__ == '__main__':
    sys.exit(main())
