import pytest
from ecpomdg_final.live.oracle_guard import assert_defender_visible


def test_rejects_hidden_stage():
    with pytest.raises(ValueError):
        assert_defender_visible({"event_type": "x", "true_stage": "CONTROL"})


def test_allows_operational_event():
    assert_defender_visible({"event_type": "iec104_select", "asset_id": "asset-field-001"})
