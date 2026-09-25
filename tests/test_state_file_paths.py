"""Cross-cutting: every package resolves its state files to the repo root."""
import os


def test_state_files_resolve_to_the_repo_root(unwalled):
    """config, llm_client and twitter_client moved under src/core and src/x
    (#114): a path computed from __file__ gains a level, and the bot would then
    read .env and write its state files under src/. The guards and editorial
    modules followed under src/guards and src/editorial (#115), the reply and
    account jobs under src/replies and src/account (#116). The state store
    resolves every JSON state file from one root (#159)."""
    from pathlib import Path
    from src.account import (account_curator, engage_bot, follow_engagers_bot,
                             follower_tracker_bot, like_bot, pin_bot)
    from src.core import (config, dynamic_strategy, evolution_store, health, history,
                          live_strategy, llm_client, personality_store, state_store)
    from src.editorial import editorial_bot, reach_report
    from src.guards import action_guard, respect_list
    from src.x import safari_hygiene, twitter_client

    repo = Path(__file__).resolve().parent.parent
    assert Path(config._PROJECT_ROOT).resolve() == repo
    assert Path(unwalled["state_root"]).resolve() == repo

    modules = (account_curator, engage_bot, follow_engagers_bot, follower_tracker_bot,
               like_bot, pin_bot, dynamic_strategy, evolution_store, health, history,
               live_strategy, llm_client, personality_store, editorial_bot, reach_report,
               action_guard, respect_list, safari_hygiene)
    stored = [v for m in modules for v in vars(m).values() if isinstance(v, state_store.StateFile)]
    assert stored
    for state_file in stored:
        assert os.path.basename(state_file.name) == state_file.name
        assert state_file.path == os.path.join(state_store.ROOT, state_file.name)

    for state_file in (twitter_client._FOLLOW_REJECTS_FILE, editorial_bot.AUDIT_FILE,
                       reach_report.REPORT_MARKDOWN):
        assert Path(state_file).resolve().parent == repo, state_file
