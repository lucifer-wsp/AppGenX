from __future__ import annotations

import httpx

from appgen.config import settings


async def web_search(query: str, num: int = 5) -> list[dict[str, str]]:
    """通过 Serper 进行联网搜索（竞品调研）。"""
    if not settings.serper_api_key:
        return [
            {
                "title": f"Mock result for: {query}",
                "snippet": "配置 SERPER_API_KEY 后可获取真实搜索结果。",
                "link": "",
            }
        ]

    headers = {
        "X-API-KEY": settings.serper_api_key,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": num}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post("https://google.serper.dev/search", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    results: list[dict[str, str]] = []
    for item in data.get("organic", []):
        results.append(
            {
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "link": item.get("link", ""),
            }
        )
    return results
