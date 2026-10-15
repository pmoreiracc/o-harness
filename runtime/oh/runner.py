"""Compatibility utilities. Agent execution belongs exclusively to native skills."""
from .native import complete as complete_reviewed


def designing(task):return (task.get('transition') or {}).get('profile')=='plans'


def intake(task):return (task.get('transition') or {}).get('profile')=='intake'
