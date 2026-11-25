import pytest

from bosun import config
from bosun.errors import ConfigError


def test_defaults():
    assert config.Config().scan_resume == "time"


def test_bad_resume():
    with pytest.raises(ConfigError):
        config.Config(scan_resume="later")


def test_load_json(tmp_path):
    path = tmp_path / "c.json"
    path.write_text('{"model": "IC-9700", "scan_dwell": 0.2}')
    cfg = config.load(path)
    assert cfg.model == "IC-9700" and cfg.scan_dwell == 0.2


def test_unknown_keys_to_extra(tmp_path):
    path = tmp_path / "c.json"
    path.write_text('{"model": "IC-9700", "future": 1}')
    assert config.load(path).extra == {"future": 1}


def test_env_override(tmp_path, monkeypatch):
    path = tmp_path / "c.json"
    path.write_text('{"model": "IC-9700"}')
    monkeypatch.setenv("BOSUN_MODEL", "FT-991A")
    assert config.load(path).model == "FT-991A"


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        config.load(tmp_path / "nope.json")


def test_negative_dwell():
    with pytest.raises(ConfigError):
        config.Config(scan_dwell=-1)
