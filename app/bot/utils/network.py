import time
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp


def parse_redirect_url(query_string: str) -> dict[str, str]:
    return {key: value[0] for key, value in parse_qs(query_string).items() if value}


async def ping_url(url: str, timeout: int = 5) -> float | None:
    try:
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            async with session.get(url=url, timeout=timeout, ssl=False) as response:
                if response.status != 200:
                    return None
                return round((time.time() - start_time) * 1000)
    except Exception:
        return None


def extract_base_url(url: str, port: int, path: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed_url = urlparse(url)

    if not parsed_url.hostname:
        raise ValueError("Invalid subscription hostname")

    scheme = parsed_url.scheme or "https"

    clean_path = (path or "sub").strip("/")

    base_url = f"{scheme}://{parsed_url.hostname}:{port}"

    return f"{base_url}/{clean_path}/"
