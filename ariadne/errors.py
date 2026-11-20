"""Errors shared by the store, the worker and the service."""


class TaskError(ValueError):
    """A refused task verb, or a task that cannot go where the caller pointed it."""
