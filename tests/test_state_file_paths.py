"""Cross-cutting: every state file resolves under state/<BOT_ACCOUNT>/."""
import os
from pathlib import Path


def test_state_files_resolve_under_the_accounts_state_folder(monkeypatch, unwalled):
    """config, llm_client and twitter_client moved under src/core and src/x
    (#114): a path computed from __file__ gains a level, and the bot would then
    read .env and write its state files under src/. The guards and editorial
    modules followed under src/guards and src/editorial (#115), the reply and
    account jobs under src/replies and src/account (#116). The state store
    resolves every JSON state file from one root (#159), which is
    state/<BOT_ACCOUNT>/ since #207, the files outside the store too."""
    from src.account import (account_curator, engage_bot, follow_engagers_bot,
                             follower_tracker_bot, like_bot, pin_bot)
    from src.core import (config, dynamic_strategy, evolution_store, health, history,
                          llm_client, personality_store, state_store)
    from src.editorial import editorial_bot, reach_report
    from src.guards import action_guard, follow_policy, respect_list
    from src.x import safari_hygiene, twitter_client

    repo = Path(__file__).resolve().parent.parent
    assert Path(config._PROJECT_ROOT).resolve() == repo
    assert Path(state_store.PROJECT_ROOT) == repo
    assert state_store.LEGACY_DIR != state_store.PROJECT_ROOT, "the conftest wall moved it"
    real_root = unwalled["state_root"]
    assert Path(real_root()) == repo / "state" / "theaishrink"
    monkeypatch.setattr(state_store, "root", real_root)

    modules = (account_curator, engage_bot, follow_engagers_bot, follower_tracker_bot,
               like_bot, pin_bot, dynamic_strategy, evolution_store, health, history,
               llm_client, personality_store, editorial_bot, reach_report,
               action_guard, follow_policy, respect_list, safari_hygiene, twitter_client)
    stored = [v for m in modules for v in vars(m).values() if isinstance(v, state_store.StateFile)]
    assert stored
    outside = (config.ACTION_LEDGER_FILE, config.REPLIED_FILE, config.ENGAGEMENT_LOG_FILE,
               editorial_bot.AUDIT_FILE, reach_report.REPORT_MARKDOWN,
               evolution_store.DIRECTIVES_FILE)
    for state_file in (*stored, *outside):
        assert os.path.basename(state_file.name) == state_file.name
        path = state_file.path if isinstance(state_file, state_store.StateFile) else os.fspath(state_file)
        assert Path(path) == repo / "state" / "theaishrink" / state_file.name, state_file

    # Another Account, another folder.
    monkeypatch.setattr(state_store.account, "current",
                        lambda: type("Account", (), {"name": "other"})())
    assert Path(os.fspath(config.ACTION_LEDGER_FILE)) == repo / "state" / "other" / "action_ledger.json"
    assert Path(stored[0].path) == repo / "state" / "other" / stored[0].name


def test_the_process_files_stay_at_the_project_root():
    """bot.log, bot.lock and autonomous_log.md belong to the process and its
    supervisors, not to an Account: run.sh tees into bot.log, the watchdog
    reads its age, and one bot.lock guards the one Safari."""
    from src.core import config, health, logger
    repo = Path(__file__).resolve().parent.parent
    assert Path(logger.LOG_FILE).resolve() == repo / "bot.log"
    assert Path(health.AUTONOMOUS_LOG_FILE).resolve() == repo / "autonomous_log.md"
    assert Path(config._PROJECT_ROOT).resolve() == repo
