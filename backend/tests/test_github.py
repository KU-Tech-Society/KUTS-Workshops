import asyncio

import httpx
import pytest

from app.github import GitHubClient, GitHubError


def test_paginated_reads_follow_page_parameters():
    requested_pages = []

    def handler(request):
        page = int(request.url.params["page"])
        requested_pages.append(page)
        items = [{"id": (page - 1) * 100 + index} for index in range(100 if page == 1 else 1)]
        return httpx.Response(200, json=items)

    client = GitHubClient("test-token")
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.github.com")
    try:
        rows = asyncio.run(client.paginated("/orgs/KU-Computing-Workshops/members"))
    finally:
        asyncio.run(client.close())

    assert len(rows) == 101
    assert requested_pages == [1, 2]


def test_permission_error_stays_an_error_not_an_empty_member_list():
    def handler(_):
        return httpx.Response(403, json={"message": "Resource not accessible by integration"})

    client = GitHubClient("secret-value")
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.github.com")
    try:
        with pytest.raises(GitHubError) as error:
            asyncio.run(client.members())
    finally:
        asyncio.run(client.close())

    assert error.value.status_code == 403
    assert "denied access" in str(error.value)
    assert "secret-value" not in str(error.value)


def test_invitation_payload_is_fixed_to_ordinary_member_and_selected_team():
    captured = {}

    def handler(request):
        captured["body"] = request.read().decode()
        return httpx.Response(201, json={"id": 13})

    client = GitHubClient("test-token")
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.github.com")
    try:
        result = asyncio.run(client.invite(44, [8], "direct_member"))
    finally:
        asyncio.run(client.close())

    assert result["id"] == 13
    assert captured["body"] == '{"invitee_id":44,"role":"direct_member","team_ids":[8]}'
