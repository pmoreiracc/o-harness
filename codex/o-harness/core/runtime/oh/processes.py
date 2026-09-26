"""Owned subprocess groups with cooperative pause and bounded cancellation."""
import contextlib
import subprocess
import threading
import time
from .storage import checkout_file, lock
from . import system


@contextlib.contextmanager
def launch(root, command, *, controlled=False, timeout=1800, **kwargs):
    from .controls import check, stopping
    gate = lock(checkout_file(root, 'oh-control.lock')) if controlled else contextlib.nullcontext()
    journal=None
    with gate:
        if controlled:
            check(root)
            from .workflow import load_run
            journal,_=load_run(root)
        child = system.spawn(command, **kwargs)
    done = threading.Event()
    cancelled = threading.Event()
    reason = []
    def watch():
        from .workflow import reduce
        stamp=None; current='running'
        deadline = time.monotonic() + timeout
        while not done.wait(0.1):
            if journal is not None:
                updated=journal.path.stat().st_mtime_ns
                if updated!=stamp:
                    current=reduce(journal.records())['status'];stamp=updated
            stop=current in ('stopping','stopped')
            if stop or time.monotonic() >= deadline:
                reason.append('stopped' if stop else 'timeout')
                cancelled.set()
                system.stop(child)
                # Keep the group leader unreaped until escalation. Its PID cannot be reused.
                done.wait(5)
                system.stop(child, force=True)
                return
    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        yield child, cancelled, reason
    finally:
        done.set()
        watcher.join(timeout=6)
        # Also reap descendants left behind by a completed command; all belong to this step.
        system.stop(child, force=True)
        child.wait(timeout=10)


def capture(root, command, *, controlled=False, timeout=900, env=None):
    # Temporary files keep draining independent of a descendant retaining stdout.
    import tempfile
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
        with launch(root, command, controlled=controlled, timeout=timeout, cwd=root,
                    env=env, stdout=output, stderr=error) as (child, cancelled, reason):
            system.wait_for_exit(child)
        output.seek(0); error.seek(0)
        return subprocess.CompletedProcess(command, child.returncode,
            output.read().decode(errors='replace'), error.read().decode(errors='replace')), reason

