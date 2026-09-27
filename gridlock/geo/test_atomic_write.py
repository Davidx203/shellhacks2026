import json

import pytest

from run_all import write_text_atomic


def test_atomic_text_write_replaces_whole_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "routes.geojson"
    write_text_atomic(target, json.dumps({"a": 1}))
    write_text_atomic(target, json.dumps({"a": 2}))
    assert json.loads(target.read_text()) == {"a": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["routes.geojson"]


def test_a_failed_atomic_write_keeps_the_old_content(tmp_path):
    target = tmp_path / "routes.geojson"
    write_text_atomic(target, "old")
    with pytest.raises(TypeError):
        write_text_atomic(target, 123)                     # not text
    assert target.read_text() == "old" and [p.name for p in tmp_path.iterdir()] == ["routes.geojson"]
