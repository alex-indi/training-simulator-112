"""Serve the prebuilt frontend in the portable distribution."""

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles


class PortableStaticFiles(StaticFiles):
    def __init__(self, directory: Path) -> None:
        super().__init__(directory=str(directory), html=True)
        self.index = directory / "index.html"

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as error:
            normalized = scope["path"].lstrip("/")
            is_backend_path = normalized == "api" or normalized.startswith(
                ("api/", "socket.io/")
            )
            if error.status_code != 404 or is_backend_path or "." in Path(normalized).name:
                raise
            return FileResponse(self.index)
