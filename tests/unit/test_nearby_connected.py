"""Which flagged access point is the one the laptop is connected to (for the AI payload)."""

from app.wireless.models import WpsInfo
from app.wireless.survey import flagged_items
from tests.unit.test_nearby_rules import MESH_NODE, OPEN, PHONE_HOTSPOT, ROUTER, ap, judge, one


def test_wps_points_at_the_connected_router_even_if_another_node_is_stronger():
    wps = WpsInfo(state="configured")
    router = ap(ROUTER, wps=wps, rssi=-60)
    node = ap(MESH_NODE, wps=wps, rssi=-35)  # stronger, but not the one you're connected to
    findings, survey = judge([router, node])
    f = one(findings, "R-WPS")
    assert f.nearby_ref == router.ref
    [item] = flagged_items(survey, findings)
    assert item.connected is True


def test_wps_falls_back_to_the_strongest_when_the_connected_ap_has_no_wps():
    node = ap(MESH_NODE, wps=WpsInfo(state="configured"), rssi=-35)
    findings, survey = judge([ap(ROUTER), node])
    assert one(findings, "R-WPS").nearby_ref == node.ref
    [item] = flagged_items(survey, findings)
    assert item.connected is False


def test_flagged_copies_are_not_marked_connected():
    hotspot = ap(PHONE_HOTSPOT, sec=OPEN)
    findings, survey = judge([ap(ROUTER), hotspot])
    [item] = flagged_items(survey, findings)
    assert item.ref == hotspot.ref and item.connected is False
