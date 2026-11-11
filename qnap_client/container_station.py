"""Container Station async client for QNAP NAS.

Uses the QNAP Container Station REST API:
- v3 API (list and actions): QTS SID as Bearer token
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .exceptions import QnapAPIError, QnapAuthError
from .models import Container

if TYPE_CHECKING:
    from .client import QnapClient


class ContainerStationClient:
    """Client for QNAP Container Station API.

    Requires an authenticated QnapClient instance — reuses its aiohttp
    session and host/port/ssl configuration.

    All requests use the QTS SID as a Bearer token (no separate CS login).
    This works on QTS 5.x and Container Station 3.x.

    Usage::

        async with QnapClient(...) as client:
            cs = ContainerStationClient(client)
            containers = await cs.get_containers()
            await cs.stop_container("my-container-id", "docker")
    """

    def __init__(self, client: QnapClient) -> None:
        """Initialize using an authenticated QnapClient."""
        self._client = client

        scheme = "https" if client._ssl else "http"  # noqa: SLF001
        base = f"{scheme}://{client._host}:{client._port}/container-station/api"  # noqa: SLF001
        self._base_v3 = f"{base}/v3"

    def _bearer_headers(self) -> dict[str, str]:
        """Return Authorization header using current QTS SID."""
        sid = self._client._sid  # noqa: SLF001
        if sid is None:
            raise QnapAuthError("QnapClient is not authenticated")
        return {"Authorization": f"Bearer {sid}"}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_containers(self) -> list[Container]:
        """Return all containers with id, name, status, image, type.

        Uses the v3 API with the QTS SID (Bearer token).

        Returns:
            List of Container dataclasses.

        Raises:
            QnapAuthError: If not authenticated.
            QnapAPIError: On bad response.
            QnapConnectionError: On network failure.
        """
        text = await self._client._request(  # noqa: SLF001
            "GET",
            f"{self._base_v3}/containers",
            headers=self._bearer_headers(),
            expected=(200,),
            invalidate_session=False,
        )
        try:
            data: dict[str, Any] = json.loads(text)
        except ValueError:
            raise QnapAPIError("Invalid Container Station JSON response") from None

        items_raw: list[dict[str, Any]] = data.get("data", {}).get("items", [])
        return [
            Container(
                id=c.get("id", ""),
                name=c.get("name", ""),
                state=c.get("status", c.get("state", "")),
                image=c.get("image", ""),
                type=c.get("type", "docker"),
            )
            for c in items_raw
        ]

    async def container_action(
        self, container_id: str, container_type: str, action: str
    ) -> None:
        """Perform an action on a container using the v3 API (Bearer token).

        Args:
            container_id: Container ID from get_containers().
            container_type: "docker" or "lxc".
            action: "start", "stop", or "restart".

        Raises:
            ValueError: If action is not valid.
            QnapAuthError: If authentication fails.
            QnapAPIError: If the action fails.
            QnapConnectionError: On network failure.
        """
        if action not in ("start", "stop", "restart"):
            raise ValueError(
                f"Invalid container action: {action!r}. Must be start, stop, or restart."
            )

        url = f"{self._base_v3}/containers/{container_type}/{container_id}/{action}"
        await self._client._request(  # noqa: SLF001
            "POST",
            url,
            headers=self._bearer_headers(),
            expected=(200, 204),
            invalidate_session=False,
        )

    async def start_container(
        self, container_id: str, container_type: str = "docker"
    ) -> None:
        """Start a container."""
        await self.container_action(container_id, container_type, "start")

    async def stop_container(
        self, container_id: str, container_type: str = "docker"
    ) -> None:
        """Stop a container."""
        await self.container_action(container_id, container_type, "stop")

    async def restart_container(
        self, container_id: str, container_type: str = "docker"
    ) -> None:
        """Restart a container."""
        await self.container_action(container_id, container_type, "restart")
