"""Register explicit native workflow entry without custom command or menu handling."""
from .storage import Refused


def enroll(root):
    """Register an explicit native invocation; preserve moved-checkout recovery."""
    from .registry import lookup, register
    try:
        entry = lookup(root)
        if entry['identity']['commit'] is None:
            from .config import name_of
            register(root, name_of(entry['project']))
    except Refused as unregistered:
        # Typing an OH command in a checkout is the person's choice to use OH here: register it as `init` would,
        # so the command they typed carries on.
        # A checkout that was registered and then moved or recreated keeps lookup's own recovery step.
        from subprocess import CalledProcessError
        from .config import ensure_project
        from .registry import index_path,register
        try:
            if index_path(root).is_file():raise unregistered
            register(root);ensure_project(root)
        except (Refused,CalledProcessError) as exc:  # Git fails outside a repository
            reason=str(exc) if isinstance(exc,Refused) else str(unregistered)
            return {'authorized':False,'onboarding':reason,'next':'Register this checkout with init as the message says, then run the command.'}
