"""HTTP response helpers for downloadable attachments."""

from urllib.parse import quote

from fastapi.responses import Response


def file_response(name: str, media_type: str, contents: bytes) -> Response:
    return Response(
        contents,
        media_type=media_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name, safe=""),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
