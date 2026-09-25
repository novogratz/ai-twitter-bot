"""bin/migrate_operator_data.py splits the Operator files from the bot's
state (#206), on fixtures shaped like the live files: whitelist.json with its
discovered tier, following_count.json with the Operator's baseline."""
import fcntl
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from src.guards import follow_policy as fp

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "migrate_operator_data.py"

OLD_WHITELIST = {
    "_README": "Curated whitelist.",
    "follow_policy": {"total_cap": 300},
    "tiers": {
        "tier1": ["TheBTCTherapist"],
        "tier2": ["morganhousel", "ParikPatelCFA"],
        "tier3": ["karpathy"],
        "tier4": ["saylor"],
        "discovered": ["unusual_whales", "Polymarket", "openai"],
    },
    "seeds": [{"priority": 1, "handle": "TheBTCTherapist", "tier": "tier1"}],
    "suggestions": [],
}
OLD_RESPECT = {"handles": {"micode": {"reason": "Tech FR", "added": "2026-05-06T10:00:00"}}}
OLD_COUNT = {"count": 3305, "baseline": 4200, "as_of": "2026-06-02",
             "note": "Operator-stated baseline.", "updated": "2026-07-19T07:55:17.090168"}


def _old_load_whitelist(raw: dict) -> dict:
    """follow_policy.load_whitelist before #206, on the mixed file."""
    def _norm(seq):
        return {str(h).lower().lstrip("@") for h in (seq or [])}
    tiers = raw.get("tiers", raw)
    t1 = _norm(tiers.get("tier1") or tiers.get("tier1_sources_targets"))
    t2 = _norm(tiers.get("tier2") or tiers.get("tier2_peers"))
    t3 = _norm(tiers.get("tier3") or tiers.get("tier3_watch"))
    t4 = _norm(tiers.get("tier4"))
    t5 = _norm(tiers.get("discovered"))
    return {"tier1": t1, "tier2": t2, "tier3": t3, "tier4": t4,
            "discovered": t5, "all": t1 | t2 | t3 | t4 | t5}


def _write(path: Path, doc) -> None:
    path.write_text(json.dumps(doc, indent=2))


@pytest.fixture
def script(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("migrate_operator_data_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ROOT", str(tmp_path))
    return mod


@pytest.fixture
def live(tmp_path, operator_folder):
    """The checkout after the pull: the backup holds the old root files, the
    Account folder the split Operator files, the root the state."""
    backup = tmp_path / "backup"
    backup.mkdir()
    _write(backup / "whitelist.json", OLD_WHITELIST)
    _write(backup / "respect_list.json", OLD_RESPECT)
    operator_whitelist = json.loads(json.dumps(OLD_WHITELIST))
    del operator_whitelist["tiers"]["discovered"]
    _write(operator_folder / "whitelist.json", operator_whitelist)
    _write(operator_folder / "respect_list.json", OLD_RESPECT)
    _write(operator_folder / "following_baseline.json",
           {k: OLD_COUNT[k] for k in ("baseline", "as_of", "note")})
    _write(tmp_path / "following_count.json", OLD_COUNT)
    return backup


def _files(*folders) -> dict:
    return {p: p.read_bytes() for folder in folders for p in sorted(folder.iterdir()) if p.is_file()}


def test_the_migration_keeps_every_value(script, live, tmp_path, operator_folder, settings_override):
    settings_override(FOLLOWING_COUNT_OVERRIDE=None)
    operator_before = _files(operator_folder)
    backup_before = _files(live)

    report = script.migrate(str(live))

    assert fp.DISCOVERED.read() == OLD_WHITELIST["tiers"]["discovered"]
    assert json.loads((tmp_path / "following_count.json").read_text()) == {
        "count": OLD_COUNT["count"], "updated": OLD_COUNT["updated"]}
    assert _files(operator_folder) == operator_before, "an Operator file was written"
    assert _files(live) == backup_before
    assert any("3 added from 3" in line for line in report)


def test_the_follow_policy_reads_the_same_whitelist_and_count(script, live, settings_override):
    settings_override(FOLLOWING_COUNT_OVERRIDE=None)

    script.migrate(str(live))

    assert fp.load_whitelist() == _old_load_whitelist(OLD_WHITELIST)
    assert fp._current_counts()[1] == OLD_COUNT["count"]
    for handle in _old_load_whitelist(OLD_WHITELIST)["all"]:
        assert fp.relation(handle) is fp.Relation.SEED, handle


def test_a_second_run_changes_nothing(script, live, tmp_path, operator_folder):
    script.migrate(str(live))
    after_first = _files(tmp_path, operator_folder)

    report = script.migrate(str(live))

    assert _files(tmp_path, operator_folder) == after_first
    assert any("0 added from 3" in line for line in report)
    assert any("nothing to drop" in line for line in report)


def test_a_promotion_since_the_backup_is_kept(script, live, tmp_path):
    _write(tmp_path / "whitelist_discovered.json", ["newfind", "openai"])

    script.migrate(str(live))

    assert fp.DISCOVERED.read() == ["newfind", "openai", "unusual_whales", "Polymarket"]


@pytest.mark.parametrize("change", [
    lambda backup, account: _write(backup / "whitelist.json", {
        **OLD_WHITELIST, "tiers": {**OLD_WHITELIST["tiers"], "tier1": ["TheBTCTherapist", "newseed"]}}),
    lambda backup, account: _write(backup / "respect_list.json", {"handles": {}}),
    lambda backup, account: _write(account / "following_baseline.json", {"baseline": 1}),
    lambda backup, account: (backup / "whitelist.json").write_text('{"tiers": {"tier1": ["karp'),
])
def test_a_difference_refuses_before_any_write(script, live, tmp_path, operator_folder, change):
    change(live, operator_folder)
    before = _files(tmp_path, operator_folder, live)

    with pytest.raises(script.Refused):
        script.migrate(str(live))

    assert _files(tmp_path, operator_folder, live) == before
    assert not (tmp_path / "whitelist_discovered.json").exists()


def test_without_the_old_whitelist_it_refuses_until_the_state_exists(script, live, tmp_path):
    (live / "whitelist.json").unlink()
    with pytest.raises(script.Refused, match="carry_state"):
        script.migrate(str(live))
    assert not (tmp_path / "whitelist_discovered.json").exists()

    _write(tmp_path / "whitelist_discovered.json", ["done"])
    assert any("nothing to carry" in line for line in script.migrate(str(live)))
    assert fp.DISCOVERED.read() == ["done"]


def test_it_refuses_while_the_bot_holds_its_lock(script, live, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["migrate_operator_data.py", "--from", str(live)])
    with open(tmp_path / "bot.lock", "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit) as exit_:
            script.main()
    assert exit_.value.code == 1
    assert "bot.lock is held" in capsys.readouterr().err
    assert not (tmp_path / "whitelist_discovered.json").exists()
