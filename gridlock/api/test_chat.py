import sqlite3

from fastapi.testclient import TestClient

from gridlock.api import main


def test_shared_chat_persists_and_supports_incremental_reads(tmp_path, monkeypatch):
    database = tmp_path / "gridlock.db"
    sqlite3.connect(database).close()
    monkeypatch.setattr(main, "DB_PATH", database)

    with TestClient(main.app) as client:
        first = client.post(
            "/messages",
            json={
                "company": "GPC",
                "sender_name": "  Alex  ",
                "kind": "job_update",
                "reference": "  Job 12  ",
                "body": "  Crew arriving at 9.  ",
            },
        )
        assert first.status_code == 201
        first_message = first.json()
        assert first_message["sender_name"] == "Alex"
        assert first_message["reference"] == "Job 12"
        assert first_message["body"] == "Crew arriving at 9."
        assert first_message["created_at"].endswith("Z")

        second = client.post(
            "/messages",
            json={
                "company": "DESC",
                "sender_name": "Sam",
                "kind": "equipment_request",
                "body": "Need a bucket truck",
            },
        )
        assert second.status_code == 201
        second_message = second.json()
        assert second_message["id"] > first_message["id"]
        assert second_message["reference"] == ""

    with TestClient(main.app) as reloaded_client:
        assert reloaded_client.get("/messages").json() == [first_message, second_message]
        assert reloaded_client.get(
            "/messages", params={"after_id": first_message["id"]}
        ).json() == [second_message]
        assert reloaded_client.get("/messages", params={"limit": 1}).json() == [second_message]


def test_chat_rejects_empty_and_invalid_messages(tmp_path, monkeypatch):
    database = tmp_path / "gridlock.db"
    sqlite3.connect(database).close()
    monkeypatch.setattr(main, "DB_PATH", database)
    valid = {"company": "GPC", "sender_name": "Alex", "kind": "tool_request", "body": "Need a wrench"}

    with TestClient(main.app) as client:
        for field, invalid_value in (
            ("sender_name", "   "),
            ("body", "   "),
            ("company", "UNKNOWN"),
            ("kind", "other"),
            ("reference", "x" * 81),
        ):
            response = client.post("/messages", json={**valid, field: invalid_value})
            assert response.status_code == 422
        assert client.get("/messages").json() == []
