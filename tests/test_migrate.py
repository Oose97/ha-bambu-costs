"""Legacy CSV import: formats, tray unpacking, and merge dedup."""

import pytest

from custom_components.bambu_costs.migrate import (
    import_files,
    parse_legacy_trays,
    read_legacy_jobs,
    read_legacy_tags,
)
from custom_components.bambu_costs.storage import BambuCostsStore


@pytest.fixture
def store(tmp_path):
    st = BambuCostsStore(str(tmp_path / "store"))
    st.ensure()
    return st


def test_five_column_tags_import_enabled(tmp_path):
    path = tmp_path / "tags.csv"
    path.write_text("PLA,#00AE42,Green,AAA,13.22\n", encoding="utf-8")
    rows = read_legacy_tags(str(path))
    assert rows[0]["disabled"] is False
    assert rows[0]["serial_2"] == ""


def test_trays_unpack_and_recover_the_price():
    rows = parse_legacy_trays("A1:Bambu PLA Basic:#00AE42:148.71g:1.966 | EXT:x:#000000:10g:0.1")
    assert len(rows) == 2
    assert rows[0]["label"] == "A1"
    assert rows[0]["weight"] == 148.71
    # never stored, recovered from cost/weight
    assert rows[0]["price"] == pytest.approx(13.22, abs=0.01)


def test_job_rows_survive_the_dropped_column(tmp_path):
    # 16-column row (with eur_per_100g) and a 15-column one (without)
    wide = "2026-01-01 10:00:00,job,1h,60,100,50,10,0.4,steel,0.1,0.5,0.02,0.52,1.04,cover.jpg,\n"
    narrow = "2026-01-02 10:00:00,job2,1h,60,100,50,10,0.4,steel,0.1,0.5,0.02,0.52,cover2.jpg,\n"
    path = tmp_path / "jobs.csv"
    path.write_text(wide + narrow, encoding="utf-8")
    jobs = read_legacy_jobs(str(path))
    assert [j["cover"] for j in jobs] == ["cover.jpg", "cover2.jpg"]


def test_merge_dedups_across_both_serials(store, tmp_path):
    store.write_tags([{
        "filament": "PLA", "color_code": "#00AE42", "color_name": "Green",
        "serial": "AAA", "cost_per_kg": 13.22, "disabled": False, "serial_2": "BBB",
    }])
    legacy = tmp_path / "legacy.csv"
    legacy.write_text("PLA,#00AE42,Green,BBB,13.22\nPETG,#000000,Black,CCC,19.99\n",
                      encoding="utf-8")
    import_files(store, str(legacy), None, None, replace=False)
    assert len(store.read_tags()) == 2, "far side of the pair must not duplicate"

    import_files(store, str(legacy), None, None, replace=False)
    assert len(store.read_tags()) == 2, "re-import must be idempotent"
