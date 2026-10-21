"""Application failures translated to HTTP responses by the API boundary."""


class ServiceError(Exception):
    def __init__(self, status_code: int, detail: str | dict):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail
