"""Owned subprocess groups with cooperative pause and bounded cancellation."""
import contextlib
import signal
import subprocess
import threading
import time
from .storage import checkout_file, lock


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
        child = subprocess.Popen(command, start_new_session=True, **kwargs)
    done = threading.Event()
    cancelled = threading.Event()
    reason = []
    import os
    def send(sig):
        try: os.killpg(child.pid, sig)
        except ProcessLookupError: pass
        except PermissionError:
            # Darwin reports EPERM for a group containing only unreaped zombies.
            rows=subprocess.check_output(['/bin/ps','-axo','pgid=,stat='],text=True).splitlines()
            live=[row.split() for row in rows if len(row.split())==2 and row.split()[0]==str(child.pid) and not row.split()[1].startswith('Z')]
            if live:raise
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
                send(signal.SIGTERM)
                # Keep the group leader unreaped until escalation. Its PID cannot be reused.
                done.wait(5)
                send(signal.SIGKILL)
                return
    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        yield child, cancelled, reason
    finally:
        done.set()
        watcher.join(timeout=6)
        # Also reap descendants left behind by a completed command; all belong to this step.
        send(signal.SIGKILL)
        child.wait(timeout=10)


def capture(root, command, *, controlled=False, timeout=900, env=None):
    # Temporary files keep draining independent of a descendant retaining stdout.
    import tempfile
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
        with launch(root, command, controlled=controlled, timeout=timeout, cwd=root,
                    env=env, stdout=output, stderr=error) as (child, cancelled, reason):
            wait_for_exit(child)
        output.seek(0); error.seek(0)
        return subprocess.CompletedProcess(command, child.returncode,
            output.read().decode(errors='replace'), error.read().decode(errors='replace')), reason


def wait_for_exit(child):
    """Observe completion without reaping the process group leader (Linux and macOS)."""
    import os
    import select
    import errno
    if hasattr(os, 'waitid'):
        while os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
            time.sleep(0.05)
    elif hasattr(select, 'kqueue'):
        with contextlib.closing(select.kqueue()) as queue:
            event=select.kevent(child.pid, filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT, fflags=select.KQ_NOTE_EXIT)
            try:
                queue.control([event], 0, 0)
                queue.control(None, 1, None)
            except ProcessLookupError:
                # Already exited, still unreaped because this scope owns the Popen object.
                pass
    else:
        raise RuntimeError('OH process ownership requires Linux waitid or macOS kqueue')
