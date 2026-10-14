import sys

import pytest

from src.core import config
from src.editorial import editorial_bot
from src.guards import action_guard
from src.x import twitter_client
from src.x.confirmed_write import WriteOutcome


@pytest.mark.parametrize("dry_run", ["0", "1"])
def test_original_permission_cannot_be_bypassed_by_env_or_direct_calls(monkeypatch, settings_override, dry_run):
    monkeypatch.setenv("DRY_RUN", dry_run)
    settings_override(MAX_ORIGINALS_PER_DAY=999)
    assert config.posts_ceiling() == 0 and config.post_targets() == (0, 0)
    assert not action_guard.can_post(action_guard.POST)[0]
    assert twitter_client.post_tweet("A sourced new original.") is WriteOutcome.REFUSED
    editorial_bot.open_startup_window()
    assert editorial_bot.startup_key() is None
    assert editorial_bot.run_editorial_cycle() is None


@pytest.mark.parametrize("flags", [{}, {"reply_only": True}, {"post_only": True}])
def test_scheduler_has_no_original_or_conversation_publishing_jobs(flags):
    from main import build_scheduler
    jobs = {job.id for job in build_scheduler(**flags).get_jobs()}
    assert not jobs & {"editorial_job", "replyback_job", "debate_job", "babysit_job", "notify_job", "pin_job"}
    if not flags.get("post_only"):
        assert {"direct_reply_job", "feed_sweep_job", "early_bird_job", "mega_watch_job"} <= jobs


def test_post_only_flag_cannot_restore_disabled_originals(monkeypatch):
    import main
    monkeypatch.setattr(sys, "argv", ["main.py", "--post-only"])
    with pytest.raises(SystemExit) as error:
        main.main()
    assert error.value.code == 2


@pytest.mark.parametrize("dry_run", ["0", "1"])
def test_no_direct_interaction_with_protected_account_even_if_allowlisted(monkeypatch, settings_override, dry_run):
    from src.x import scraper
    monkeypatch.setenv("DRY_RUN", dry_run)
    settings_override(PROFILE_VISIT_ALLOWLIST="elonmusk", FOLLOW_WHITELIST_ONLY=False)
    url = "https://x.com/ElonMusk/status/1234567890123456789"
    assert twitter_client.reply_to_tweet(url, "A useful technical observation.") is WriteOutcome.REFUSED
    assert twitter_client.like_tweet(url) is twitter_client.LikeOutcome.BLOCKED
    assert twitter_client.follow_account("@ElonMusk") is twitter_client.FollowOutcome.BLOCKED
    assert twitter_client.pin_own_tweet(url) is WriteOutcome.REFUSED
    assert not scraper._profile_visit_allowed("elonmusk")
    assert twitter_client.visit_profile_and_like("elonmusk") == []
