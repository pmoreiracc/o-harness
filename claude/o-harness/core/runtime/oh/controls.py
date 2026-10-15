"""Read legacy executor ownership before adopting historical evidence."""
from .storage import Refused, checkout_file, lock


def busy(root):
    try:
        with lock(checkout_file(root, 'oh-runner.lock'), wait=False):
            return False
    except Refused:
        return True
