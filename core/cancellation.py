"""Cancellation signal shared by Qt tasks and headless helpers."""
class TaskCancelled(RuntimeError):
    pass
