from routes import PowerGrid, attach_routes


def way(points, voltage="115000"):
    return {"tags": {"voltage": voltage}, "geometry": [{"lat": la, "lon": lo} for la, lo in points]}


LINE = way([(32.00, -81.00), (32.00, -81.05), (32.00, -81.10)])
OTHER_KV = way([(32.00, -81.10), (32.00, -81.20)], voltage="230000")


def test_route_follows_same_voltage_line_and_reports_miles():
    grid = PowerGrid([LINE])
    miles, coords = grid.route(115, (32.0, -81.0), (32.0, -81.1), cutoff=30)
    assert 5.5 < miles < 6.5
    assert coords[0] == (32.0, -81.0) and coords[-1] == (32.0, -81.1)
    assert len(coords) >= 3


def test_no_route_across_a_different_voltage_or_gap():
    grid = PowerGrid([LINE, OTHER_KV])
    assert grid.route(115, (32.0, -81.0), (32.0, -81.2), cutoff=30) is None
    assert grid.route(69, (32.0, -81.0), (32.0, -81.1), cutoff=30) is None


def test_multi_voltage_way_serves_both_voltages():
    grid = PowerGrid([way([(32.0, -81.0), (32.0, -81.05)], voltage="230000;115000")])
    assert grid.route(115, (32.0, -81.0), (32.0, -81.05), cutoff=30)
    assert grid.route(230, (32.0, -81.0), (32.0, -81.05), cutoff=30)


def test_attach_routes_sets_route_mi_only_where_found():
    grid = PowerGrid([LINE])
    found = {"project_id": "P1", "voltage_kv": "115", "lat_a": 32.0, "lon_a": -81.0, "lat_b": 32.0, "lon_b": -81.1}
    single = {"project_id": "P2", "voltage_kv": "115", "lat_a": 32.0, "lon_a": -81.0, "lat_b": "", "lon_b": ""}
    novolt = {"project_id": "P3", "voltage_kv": "", "lat_a": 32.0, "lon_a": -81.0, "lat_b": 32.0, "lon_b": -81.1}
    features = attach_routes([found, single, novolt], grid)
    assert [f["properties"]["project_id"] for f in features] == ["P1"]
    assert found["route_mi"] > 5 and single["route_mi"] == "" and novolt["route_mi"] == ""
