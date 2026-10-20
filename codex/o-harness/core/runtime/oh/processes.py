"""Bounded configured-check subprocesses; native hosts own agent cancellation."""
import contextlib
import json
import os
import subprocess
import signal
import threading
import time
from . import system


@contextlib.contextmanager
def interruptible():
    """Let native shell termination unwind owned cleanup instead of killing Python."""
    previous = {}
    if threading.current_thread() is threading.main_thread():
        def interrupted(signum, frame):
            # A second native termination during cleanup must not cut it short.
            for number in previous:
                signal.signal(number, signal.SIG_IGN)
            raise KeyboardInterrupt
        for number in (signal.SIGINT, signal.SIGTERM):
            previous[number] = signal.signal(number, interrupted)
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


@contextlib.contextmanager
def launch(root, command, *, timeout=None, interrupt=False, **kwargs):
    from . import cancellation
    context = cancellation.command_context()
    ticket, stop = cancellation.started_command(context, command) if context else (None, None)
    if context:
        from .storage import state_home
        kwargs['env'] = dict(kwargs.get('env') or os.environ, OH_OWNED_COMMAND=json.dumps(
            {'attempt': context['attempt'], 'root': str(context['root'].resolve()), 'data_home': str(state_home())}))
    try:
        child = system.spawn(command, on_spawn=(lambda child: cancellation.spawned_command(context, ticket, child))
                             if ticket else None, **kwargs)
    except BaseException:
        if ticket:
            cancellation.ended_command(context, ticket, -1)
        raise
    done = threading.Event()
    cancelled = threading.Event()
    reason = []
    def watch():
        deadline = time.monotonic() + timeout if timeout is not None else None
        while not done.wait(0.1):
            observed_stop = False
            if context:
                try:
                    if context['receipt'] is not None:
                        _, observed_stop = cancellation.observe(context)
                    else:
                        cancellation.poll(context['root'], attempt=context['attempt'])
                except Exception:
                    # Lost cancellation evidence cannot leave the command running unchecked.
                    reason.append('control_unavailable')
                    cancelled.set()
                    system.stop(child, force=True)
                    return
            if system.wait_for_exit(child, timeout=0):
                # An exited worker's descendants may still hold its output pipe open.
                # Close them before the consumer waits forever for EOF; keep the leader unreaped.
                system.stop(child, force=True)
                return
            stopped = observed_stop or stop is not None and stop.exists()
            if stopped or deadline is not None and time.monotonic() >= deadline:
                reason.append('native_stop' if stopped else 'timeout')
                cancelled.set()
                system.stop(child, interrupt=interrupt)
                # Keep the group leader unreaped until escalation. Its PID cannot be reused.
                done.wait(.2 if stopped else 5)
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
        if ticket:
            cancellation.ended_command(context, ticket, child.returncode)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                with contextlib.suppress(BrokenPipeError):stream.close()


def capture(root, command, *, timeout=900, env=None):
    # Temporary files keep draining independent of a descendant retaining stdout.
    import tempfile
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
        with launch(root, command, timeout=timeout, cwd=root,
                    env=env, stdout=output, stderr=error) as (child, cancelled, reason):
            system.wait_for_exit(child)
        output.seek(0); error.seek(0)
        return subprocess.CompletedProcess(command, child.returncode,
            output.read().decode(errors='replace'), error.read().decode(errors='replace')), reason
