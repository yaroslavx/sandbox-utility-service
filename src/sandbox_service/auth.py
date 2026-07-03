from fastapi import Header


def require_internal_service(authorization: str | None = Header(default=None)) -> None:
    """Auth boundary placeholder.

    MVP intentionally does not enforce auth. Keeping this dependency on the
    route makes adding a bearer token or service-mesh assertion later a small,
    localized change.
    """

    _ = authorization
