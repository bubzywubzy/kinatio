from pathlib import Path

from kinatio.domain.models import SystemState
from kinatio.runtime.cache import JSONStateCache


def test_cache_round_trip(tmp_path: Path) -> None:
    cache = JSONStateCache(tmp_path / "state.json")
    state = SystemState()

    cache.save(state)
    loaded = cache.load()

    assert loaded is not None
    assert loaded.model_dump() == state.model_dump()


def test_cache_load_returns_none_and_quarantines_invalid_json(tmp_path: Path) -> None:
    cache_path = tmp_path / "state.json"
    cache_path.write_text("{not json", encoding="utf-8")
    cache = JSONStateCache(cache_path)

    loaded = cache.load()

    assert loaded is None
    assert not cache_path.exists()
    quarantined = list(tmp_path.glob("state.json.corrupt.*"))
    assert len(quarantined) == 1


def test_cache_load_returns_none_and_quarantines_schema_mismatch(tmp_path: Path) -> None:
    cache_path = tmp_path / "state.json"
    cache_path.write_text('{"hardware":"invalid"}', encoding="utf-8")
    cache = JSONStateCache(cache_path)

    loaded = cache.load()

    assert loaded is None
    assert not cache_path.exists()
    quarantined = list(tmp_path.glob("state.json.corrupt.*"))
    assert len(quarantined) == 1


def test_cache_save_creates_file_with_restrictive_permissions(tmp_path: Path) -> None:
    cache_path = tmp_path / "state.json"
    cache = JSONStateCache(cache_path)

    cache.save(SystemState())

    assert cache_path.exists()
    assert cache_path.stat().st_mode & 0o777 == 0o600


def test_cache_save_cleans_up_temp_file_when_atomic_replace_fails(tmp_path: Path, monkeypatch) -> None:
    cache_path = tmp_path / "state.json"
    cache = JSONStateCache(cache_path)

    def fail_replace(self: Path, target: Path) -> Path:
        del self, target
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)

    cache.save(SystemState())

    assert not cache_path.exists()
    assert list(tmp_path.glob(f".{cache_path.name}*.tmp")) == []


def test_cache_load_returns_none_after_documented_cache_reset(tmp_path: Path) -> None:
    cache_path = tmp_path / ".cache" / "kinatio" / "state.json"
    cache = JSONStateCache(cache_path)

    cache.save(SystemState())
    cache_path.unlink()

    assert cache.load() is None