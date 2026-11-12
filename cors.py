LOCAL_FRONTEND_ORIGINS = (
    "http://127.0.0.1:5500",
    "http://localhost:5500",)


def get_allowed_origins(raw: str | None):
    if raw is None or not raw.strip():
        return list(LOCAL_FRONTEND_ORIGINS)

    origins: list[str] = []

    for value in raw.split(","):
        origin = value.strip().rstrip("/")

        if not origin:
            continue

        if origin == "*":
            raise ValueError("Wildcard CORS origin is not allowed")

        if origin not in origins:
            origins.append(origin)

    return origins or list(LOCAL_FRONTEND_ORIGINS)
