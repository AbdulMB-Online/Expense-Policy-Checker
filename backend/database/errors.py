"""Shared storage exceptions and driver-error translation."""

import sqlite3
from functools import wraps


class StorageError(Exception):
    """The underlying submission storage could not be read or written."""


class SubmissionConflictError(Exception):
    """A saved request key was reused with different claim details."""


class ReceiptNotFoundError(Exception):
    """The requested claim has no receipt in this workspace."""


def storage_errors(operation):
    """Keep driver and filesystem failures inside the database boundary."""

    @wraps(operation)
    def wrapped(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except (sqlite3.Error, OSError) as error:
            raise StorageError("Submission storage is unavailable.") from error

    return wrapped


class AccessError(Exception):
    """The current account cannot perform this operation."""


class RecordNotFoundError(Exception):
    """The requested record is missing or invisible to the current account."""
