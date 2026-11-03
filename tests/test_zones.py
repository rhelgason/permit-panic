from datetime import datetime, timedelta, timezone

from permit_panic import zones

INDEX = {"built": datetime.now(timezone.utc).isoformat(), "permits": {
    "4675317": {"name": "Mount Rainier National Park Wilderness and Climbing Permits",
                "zones": {"69": "Camp Muir Alpine Camp", "75": "Muir Snowfield Alpine Zone", "1": "Camp Schurman"}},
    "445859": {"name": "Yosemite National Park Wilderness Permits",
               "zones": {"17": "Happy Isles->Little Yosemite Valley", "5": "John Muir Trail"}},
}}


def test_zone_name_found_inside_its_permit():
    [top, *_] = zones.search(INDEX, "camp muir")
    assert (top.entity_type, top.entity_id, top.division_id, top.name) == ("zone", "4675317", "69", "Camp Muir Alpine Camp")


def test_words_can_come_from_the_permit_name():
    hits = zones.search(INDEX, "rainier muir")
    assert {h.division_id for h in hits} == {"69", "75"}  # not Yosemite's John Muir Trail
    assert zones.search(INDEX, "rainier") == []  # a permit-name-only match is the site search's job


def test_no_index_or_empty_query():
    assert zones.search(None, "camp muir") == [] and zones.search(INDEX, "  ") == []


def test_stale_after_a_week():
    assert zones.stale(None) and zones.stale({"built": INDEX["built"], "permits": {}})
    assert not zones.stale(INDEX)
    assert zones.stale(INDEX, now=datetime.now(timezone.utc) + timedelta(days=8))


def test_build_and_save_roundtrip(tmp_path):
    class Api:
        def list_permits(self):
            return [("1", "One"), ("2", "Broken")]

        def permit_content(self, pid):
            if pid == "2":
                raise OSError("boom")
            return {"name": "One", "divisions": {"a": {"name": "Zone A"}}}

    index = zones.build(Api(), previous={}, retry_waits=(0, 0))
    assert index["permits"] == {"1": {"name": "One", "zones": {"a": "Zone A"}}}  # broken listing skipped
    zones.save(tmp_path / "z.json", index)
    assert zones.load(tmp_path / "z.json")["permits"] == index["permits"]


def test_bundled_snapshot_finds_camp_muir_with_no_local_index(tmp_path):
    index = zones.load_best(tmp_path / "missing.json")
    assert len(index["permits"]) > 100
    [top, *_] = zones.search(index, "camp muir")
    assert (top.name, top.entity_id) == ("Camp Muir Alpine Camp", "4675317")
    assert zones.describe(index).startswith("Searching 3,")


def test_local_index_overrides_bundled_per_permit(tmp_path):
    local = {"built": INDEX["built"], "permits": {"4675317": {"name": "Rainier", "zones": {"69": "Renamed Camp"}}}}
    zones.save(tmp_path / "z.json", local)
    merged = zones.load_best(tmp_path / "z.json")["permits"]
    assert merged["4675317"]["zones"] == {"69": "Renamed Camp"}  # the fresher local copy wins
    assert len(merged) > 100  # everything else still comes from the bundled snapshot


def test_failed_permit_is_retried_then_kept_from_previous():
    calls = {"rainier": 0}

    class Flaky:
        def list_permits(self):
            return [("1", "Glacier"), ("4675317", "Rainier"), ("9", "Gone")]

        def permit_content(self, pid):
            if pid == "4675317":
                calls["rainier"] += 1
                raise ValueError("truncated JSON")  # a cut-off 1 MB response
            if pid == "9":
                raise OSError("timed out")
            return {"name": "Glacier", "divisions": {"g": {"name": "Muir Creek Spike Camp"}}}

    index = zones.build(Flaky(), previous=INDEX, retry_waits=(0, 0))
    assert calls["rainier"] == 3  # first try + two retries
    assert index["permits"]["4675317"]["zones"]["69"] == "Camp Muir Alpine Camp"  # kept, not dropped
    assert "9" not in index["permits"] and set(index["failed"]) == {"4675317", "9"}


def test_partial_local_index_still_finds_bundled_permits(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled.json"
    zones.save(bundled, INDEX)
    monkeypatch.setattr(zones, "BUNDLED", bundled)
    local = {"built": INDEX["built"], "permits": {"445859": INDEX["permits"]["445859"]}}  # Rainier missing
    zones.save(tmp_path / "local.json", local)
    [top, *_] = zones.search(zones.load_best(tmp_path / "local.json"), "camp muir")
    assert top.name == "Camp Muir Alpine Camp"
