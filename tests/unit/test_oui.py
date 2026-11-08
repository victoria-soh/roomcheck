from app.fingerprint.oui import OUI_FILE, load_oui, lookup_vendor


def test_bundled_list_is_present_and_large():
    assert OUI_FILE.exists()
    assert OUI_FILE.read_text(encoding="utf-8").startswith("# IEEE MA-L")
    assert len(load_oui()) > 30000


def test_lookup_known_vendors():
    assert lookup_vendor("38:42:0B:00:00:84") == "Sonos, Inc."
    assert lookup_vendor("cc-ba-bd-00-00-01") == "TP-Link Systems Inc."
    assert "Hikvision" in lookup_vendor("00:bc:99:aa:bb:cc")


def test_private_mac_has_no_vendor():
    # 0x3A has the locally administered bit set; even if a prefix existed it isn't used.
    assert lookup_vendor("3a:00:5e:00:53:84") is None
    assert lookup_vendor("da:a1:19:20:30:40") is None


def test_missing_or_bad_mac():
    assert lookup_vendor(None) is None
    assert lookup_vendor("not a mac") is None
    assert lookup_vendor("00:00:01:00:00:00", table={}) is None
