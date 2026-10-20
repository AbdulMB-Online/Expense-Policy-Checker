"""Minimal file interface shared by HTTP uploads and in-memory callers."""

from typing import BinaryIO, Protocol


class UploadedFile(Protocol):
    filename: str | None
    file: BinaryIO
