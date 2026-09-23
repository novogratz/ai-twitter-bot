"""Cross-cutting: every package resolves its state files to the repo root."""
import pytest

pytestmark = pytest.mark.usefixtures("isolate_dedup")


def test_state_files_resolve_to_the_repo_root():
    """config, llm_client and twitter_client moved under src/core and src/x
    (#114): a path computed from __file__ gains a level, and the bot would then
    read .env and write its state files under src/. The guards and editorial
    modules followed under src/guards and src/editorial (#115), the reply and
    account jobs under src/replies and src/account (#116)."""
    from pathlib import Path
    from src.account import (account_curator, engage_bot, follow_engagers_bot,
                             follower_tracker_bot, like_bot, pin_bot)
    from src.core import config, llm_client
    from src.editorial import editorial_bot, reach_report
    from src.guards import action_guard, respect_list
    from src.replies import first_hour_babysitter
    from src.x import twitter_client

    repo = Path(__file__).resolve().parent.parent
    assert Path(config._PROJECT_ROOT).resolve() == repo
    for state_file in (llm_client._CODEX_LOCKOUT_FILE, twitter_client._FOLLOW_REJECTS_FILE,
                       action_guard._FOLLOWING_COUNT_FILE, respect_list.RESPECT_FILE,
                       editorial_bot.STATE_FILE, editorial_bot.AUDIT_FILE,
                       reach_report.REPORT_FILE, reach_report.REPORT_MARKDOWN,
                       first_hour_babysitter.HISTORY_FILE,
                       account_curator.TRACKED_FILE, account_curator.TARGETS_LOG_FILE,
                       engage_bot.FOLLOWED_FILE, follow_engagers_bot.STATE_FILE,
                       follower_tracker_bot.FOLLOWER_HISTORY_FILE,
                       like_bot.LIKE_BOT_STATE_FILE,
                       pin_bot.PIN_HISTORY_FILE, pin_bot.PIN_STATE_FILE):
        assert Path(state_file).resolve().parent == repo, state_file
