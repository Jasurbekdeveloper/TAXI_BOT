import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


@pytest.fixture
def agg(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AGG_FILE", tmp_path / "a.json")
    monkeypatch.setattr(config, "BROADCAST_MIN_INTERVAL_MIN", 30)
    monkeypatch.setattr(config, "BROADCAST_MAX_PER_DAY", 3)
    import aggregator
    importlib.reload(aggregator)
    return aggregator


def test_text_and_interval(agg):
    assert agg.get_text() == "" and agg.interval_min() == 30
    agg.set_text("  Yo'lovchi izlayman  ")
    assert agg.get_text() == "Yo'lovchi izlayman"
    agg.set_interval(5)                      # minimaldan past -> 30 ga ko'tariladi
    assert agg.interval_min() == 30
    agg.set_interval(60)
    assert agg.interval_min() == 60


def test_groups_select(agg):
    agg.set_groups([(-100, "Termiz Taksi"), (-200, "Denov Taksi")])
    assert set(agg.groups()) == {"-100", "-200"} and agg.active_group_ids() == []
    assert agg.toggle_group(-100) is True
    assert agg.active_group_ids() == [-100] and agg.is_active_group(-100) and not agg.is_active_group(-200)
    agg.set_groups([(-100, "Termiz Taksi 2")])      # -200 chiqib ketdi, -100 on holati saqlanadi
    assert "-200" not in agg.groups() and agg.groups()["-100"]["on"]
    assert agg.groups()["-100"]["title"] == "Termiz Taksi 2"
    assert not agg.toggle_group(-999)               # yo'q guruh


def test_due_requires_config(agg):
    now = 100000                                     # last_round=0 bo'lgani uchun oraliqdan katta
    assert not agg.due(now=now)                      # hech narsa sozlanmagan
    agg.set_text("x"); agg.set_groups([(-1, "A")]); agg.toggle_group(-1)
    assert not agg.due(now=now)                      # active emas
    agg.set_active(True)
    assert agg.due(now=now)


def test_due_interval_and_cap(agg):
    agg.set_text("x"); agg.set_groups([(-1, "A")]); agg.toggle_group(-1); agg.set_active(True)
    t = 10000
    for _ in range(3):                               # kuniga 3 sikl (cap)
        assert agg.due(now=t)
        agg.start_round(now=t)
        assert not agg.due(now=t)                     # hozirgina yurdi
        t += 31 * 60                                  # oraliq o'tdi
    assert not agg.due(now=t)                         # kunlik limit tugadi


def test_first_notice_and_report(agg):
    agg.set_groups([(-1, "Termiz"), (-2, "Denov")])
    assert agg.start_round(now=100) is True           # birinchi marta
    agg.mark_notified()
    assert agg.start_round(now=200) is False
    agg.record_post(-1, now=100); agg.record_post(-1, now=100); agg.record_post(-2, now=100)
    assert agg.report(now=150) == [("Termiz", 2), ("Denov", 1)]
    agg.record_post(-1, now=100000)                   # 24 soatdan keyin: eskilari tozalanadi
    assert agg.report(now=100000) == [("Termiz", 1)]
