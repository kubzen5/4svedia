from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


class ApiKeyLocation(str, Enum):
    """Optional automatic API-key placement."""

    NONE = "none"
    HEADER = "header"
    QUERY = "query"
    PATH = "path"


@dataclass(frozen=True, slots=True)
class ApiConfig:
    """Configuration shared by API clients: base URL and API key."""

    api_url: str | None
    api_key: str | None
    api_key_location: ApiKeyLocation = ApiKeyLocation.NONE
    api_key_name: str = "X-API-Key"
    api_key_prefix: str = ""
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        api_url = (self.api_url or "").strip()
        api_key = (self.api_key or "").strip()

        if not api_url:
            raise ValueError("api_url cannot be empty")
        if not api_url.startswith(("http://", "https://")):
            raise ValueError("api_url must start with http:// or https://")
        if not api_key:
            raise ValueError("api_key cannot be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        object.__setattr__(self, "api_url", api_url.rstrip("/") + "/")
        object.__setattr__(self, "api_key", api_key)

    @classmethod
    def from_env(
        cls,
        prefix: str,
        **kwargs: Any,
    ) -> "ApiConfig":
        """Create a config from PREFIX_API_URL and PREFIX_API_KEY."""

        normalized_prefix = prefix.strip().upper()
        return cls(
            api_url=os.getenv(f"{normalized_prefix}_API_URL"),
            api_key=os.getenv(f"{normalized_prefix}_API_KEY"),
            **kwargs,
        )


class ApiClientError(RuntimeError):
    """Raised when an API request cannot be completed successfully."""


class ApiClient:
    """Reusable HTTP client based on a common api_url/api_key configuration."""

    def __init__(self, config: ApiConfig) -> None:
        self.config = config

    @property
    def api_url(self) -> str:
        return self.config.api_url  # type: ignore[return-value]

    @property
    def api_key(self) -> str:
        return self.config.api_key  # type: ignore[return-value]

    def _redact(self, value: str) -> str:
        return value.replace(self.api_key, "***")

    def _prepare_url(
        self,
        endpoint: str,
        query: Mapping[str, Any] | None = None,
    ) -> str:
        endpoint = endpoint.lstrip("/")

        if self.config.api_key_location is ApiKeyLocation.PATH:
            if "{api_key}" not in endpoint:
                raise ValueError(
                    "PATH authentication requires an {api_key} placeholder in endpoint"
                )
            endpoint = endpoint.replace("{api_key}", quote(self.api_key, safe=""))

        url = urljoin(self.api_url, endpoint)
        split = urlsplit(url)
        query_items = list(parse_qsl(split.query, keep_blank_values=True))

        if query:
            query_items.extend((key, str(value)) for key, value in query.items())

        if self.config.api_key_location is ApiKeyLocation.QUERY:
            query_items.append(
                (
                    self.config.api_key_name,
                    f"{self.config.api_key_prefix}{self.api_key}",
                )
            )

        return urlunsplit(
            (
                split.scheme,
                split.netloc,
                split.path,
                urlencode(query_items),
                split.fragment,
            )
        )

    def _prepare_headers(
        self,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        prepared = {
            "Accept": "application/json, text/csv, */*",
            "User-Agent": "multi-api-client/1.1",
        }
        if headers:
            prepared.update(headers)

        if self.config.api_key_location is ApiKeyLocation.HEADER:
            prepared[self.config.api_key_name] = (
                f"{self.config.api_key_prefix}{self.api_key}"
            )

        return prepared

    def request_bytes(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> bytes:
        url = self._prepare_url(endpoint, query)
        request = Request(
            url=url,
            data=body,
            headers=self._prepare_headers(headers),
            method=method.upper(),
        )

        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                return response.read()
        except HTTPError as exc:
            raise ApiClientError(
                f"API returned HTTP {exc.code} for {self._redact(url)}"
            ) from exc
        except URLError as exc:
            raise ApiClientError(
                f"Could not connect to {self._redact(url)}: {exc.reason}"
            ) from exc

    def get_json(
        self,
        endpoint: str,
        *,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        payload = self.request_bytes(
            endpoint,
            query=query,
            headers={"Accept": "application/json", **(headers or {})},
        )
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiClientError("API response is not valid UTF-8 JSON") from exc

    def download(
        self,
        endpoint: str,
        destination: str | Path,
        *,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Path:
        """Download a file atomically and return its destination path."""

        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.request_bytes(endpoint, query=query, headers=headers)

        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        temporary_path = Path(temporary_name)

        try:
            with os.fdopen(file_descriptor, "wb") as temporary_file:
                temporary_file.write(payload)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            temporary_path.replace(target)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

        return target

    def post_json(
            self,
            endpoint: str,
            payload: Any,
            *,
            query: Mapping[str, Any] | None = None,
            headers: Mapping[str, str] | None = None,
    ) -> Any:
        """Wyślij POST z JSON-em i zwróć odpowiedź JSON."""

        try:
            body = json.dumps(
                payload,
                ensure_ascii=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Payload musi być możliwy do zapisania jako JSON"
            ) from exc

        response = self.request_bytes(
            endpoint,
            method="POST",
            query=query,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                **(headers or {}),
            },
            body=body,
        )

        if not response:
            return None

        try:
            return json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiClientError(
                "Odpowiedź API nie jest poprawnym JSON-em UTF-8"
            ) from exc

class ApiRegistry:
    """Named collection of clients for applications using multiple APIs."""

    def __init__(self) -> None:
        self._clients: dict[str, ApiClient] = {}

    def register(self, name: str, config: ApiConfig) -> ApiClient:
        normalized_name = name.strip().lower()
        if not normalized_name:
            raise ValueError("API name cannot be empty")

        client = ApiClient(config)
        self._clients[normalized_name] = client
        return client

    def get(self, name: str) -> ApiClient:
        normalized_name = name.strip().lower()
        try:
            return self._clients[normalized_name]
        except KeyError as exc:
            available = ", ".join(sorted(self._clients)) or "none"
            raise KeyError(
                f"Unknown API client '{name}'. Registered clients: {available}"
            ) from exc
