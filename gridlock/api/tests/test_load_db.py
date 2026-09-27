import sqlite3
import sys

import pytest

from api import load_db


def write_processed(root, projects_rows):
    folder = root / "data" / "processed"
    folder.mkdir(parents=True)
    (folder / "projects.csv").write_text("project_id,project_name\n" + "".join(f"{i},{n}\n" for i, n in projects_rows))
    (folder / "overlaps.csv").write_text("overlap_id,rank\nOVL_1,1\n")
    (folder / "briefs.csv").write_text("overlap_id\nOVL_1\n")


def run_main(monkeypatch, root):
    monkeypatch.setattr(load_db, "ROOT", root)
    monkeypatch.setattr(load_db, "DB_PATH", root / "gridlock.db")
    monkeypatch.setattr(sys, "argv", ["load_db", "--source", "processed"])
    load_db.main()


def test_reload_swaps_the_database_atomically(tmp_path, monkeypatch):
    old = sqlite3.connect(tmp_path / "gridlock.db")
    old.execute("CREATE TABLE projects (project_id TEXT, project_name TEXT)")
    old.execute("INSERT INTO projects VALUES ('OLD', 'old')")
    old.commit()
    old.close()
    write_processed(tmp_path, [("P1", "New one")])
    run_main(monkeypatch, tmp_path)
    rows = sqlite3.connect(tmp_path / "gridlock.db").execute("SELECT project_id FROM projects").fetchall()
    assert rows == [("P1",)]
    assert not (tmp_path / "gridlock.db.tmp").exists()


def test_a_failed_load_keeps_the_old_database_and_removes_the_temp_file(tmp_path, monkeypatch):
    old = sqlite3.connect(tmp_path / "gridlock.db")
    old.execute("CREATE TABLE projects (project_id TEXT)")
    old.execute("INSERT INTO projects VALUES ('OLD')")
    old.commit()
    old.close()
    folder = tmp_path / "data" / "processed"
    folder.mkdir(parents=True)
    (folder / "projects.csv").write_text("project_id\nNEW\n")       # loads fine, then overlaps.csv is missing
    with pytest.raises(FileNotFoundError):
        run_main(monkeypatch, tmp_path)
    assert sqlite3.connect(tmp_path / "gridlock.db").execute("SELECT project_id FROM projects").fetchall() == [("OLD",)]
    assert not (tmp_path / "gridlock.db.tmp").exists()
