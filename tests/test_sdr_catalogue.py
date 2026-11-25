from bosun.control import describe_catalogue
from bosun.sdr import catalogue as sdrcat


def test_rtlsdr_listed_with_radios():
    names = sdrcat.picker_names()
    assert any("RTL-SDR" in n for n in names)
    assert any("NESDR SMArTee XTR" in n for n in names)
    assert any("HackRF One" in n for n in names)
    assert "RTL-SDR" in describe_catalogue()


def test_lookup_and_match():
    e = sdrcat.lookup("RTL-SDR Blog V4" + sdrcat.SUFFIX)
    assert e and e["source"] == "rtlsdr"
    assert sdrcat.match_source(e, ["demo", "rtlsdr:rtl:0"]) == "rtlsdr:rtl:0"
    assert sdrcat.match_source(e, ["demo"]) is None
    assert not sdrcat.is_sdr("IC-9100")
