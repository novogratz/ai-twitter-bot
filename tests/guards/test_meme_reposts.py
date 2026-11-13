from datetime import timedelta
import csv
import json

import pytest

from src.video import repost_review as video
from src.account import meme_repost_bot as job
from src.core import config
from src.guards import action_guard as ag, active_hours, meme_repost_store as store, repost_store
from src.x import twitter_client as tc, repost_page, safari, x_urls
from tests.helpers import clock, fresh


def evidence(page, **verdict):
    frames = [dict(at=i + .5, sha256=str(i) * 64) for i in range(6)]
    return dict(revision=video.REVISION, url=page['url'], source_hash=store.digest(page['text']),
                media_id=page['media_id'], duration=6, frames=frames, fingerprint=video.frame_digest(frames),
                verdict=dict(approved=True, ai_related=True, funny=True, safe_to_amplify=True,
                             all_samples_reviewed=True, visual_joke_supported=True, needs_unavailable_audio=False,
                             humor_score=8, reason='visual joke', observations=[dict(at=i+.5, observation='observed action') for i in (0,2,5)], **verdict))


def approve(page):
    store.review(page['url'], page['text'], True, 'visual joke', 8, video_evidence=evidence(page))


@pytest.fixture
def meme(monkeypatch, settings_override, memory_ledger):
    settings_override(MEME_REPOST_ENABLED=True, VIDEO_ENABLED=True, MEME_REPOST_DAILY_CAP=2,
                      MEME_REPOST_INTERVAL_MINUTES=30)
    monkeypatch.setenv('DRY_RUN', '0')
    for key, value in (('_candidates', {}), ('_recent', {}), ('_retry_after', {}), ('_seeded', True)):
        monkeypatch.setattr(store, key, value)
    clock(monkeypatch, active_hours.now_local())
    return dict(url=fresh('comedian'), text='My AI agent spent all night automating a task I could have done in two minutes.',
                language='en', likes=11, views=929, has_video=True, media_id='123456', state='ready')


@pytest.mark.parametrize('changes', [dict(has_video=False), dict(is_reply=True), dict(text='Crypto trading giveaway AI'),
                                    dict(text='My coffee is cold'), dict(url='https://elsewhere.test/comedian/status/123')])
def test_ai_video_and_exact_original_are_required(meme, changes):
    assert store.qualifies(meme)
    assert not store.qualifies({**meme, **changes})


@pytest.mark.parametrize('counts', [dict(likes=0, views=0), dict(likes=None, views=None), dict(likes=11, views=929)])
def test_funny_video_needs_no_popularity_threshold(meme, counts):
    assert store.qualifies({**meme, **counts})


def test_optional_counter_floor_remains_exact(meme, settings_override):
    settings_override(MEME_REPOST_MIN_LIKES=3)
    assert not store.qualifies({**meme, 'likes': None})
    assert not store.qualifies({**meme, 'likes': True})


def test_budget_dedup_and_uncertain_claim_survive_rereads(meme, monkeypatch):
    url = meme['url']
    approve(meme)
    assert ag.can_post(ag.MEME_REPOST, target=url)[0]
    assert not ag.can_post(ag.MEME_REPOST)[0]
    assert not ag.can_post(ag.RETWEET, target=url)[0]
    assert repost_store.claim(url, kind='meme')
    second = {**meme, 'url': fresh('comedian', n=1)}
    approve(second)
    assert 'uncertain' in store.refusal(second['url'])
    repost_store.remember(url, 'shipped', kind='meme')
    assert 'spacing' in store.refusal(second['url'])
    clock(monkeypatch, active_hours.now_local() + timedelta(minutes=30))
    assert repost_store.claim(second['url'], kind='meme')
    repost_store.remember(second['url'], 'shipped', kind='meme')
    assert 'cap' in store.refusal()


def test_twenty_is_a_ceiling_not_a_publication_target(meme, settings_override):
    settings_override(MEME_REPOST_DAILY_CAP=20)
    for i in range(20):
        ag.record(ag.MEME_REPOST, fresh('comedian', n=i))
    assert 'cap' in store.refusal()
    assert store.next_candidate() is None


@pytest.fixture
def browser(meme, monkeypatch):
    approve(meme)
    monkeypatch.setattr(safari, 'open_url', lambda *_: True)
    monkeypatch.setattr(safari, 'close_front_tab', lambda: None)
    monkeypatch.setattr(tc.time, 'sleep', lambda *_: None)
    return []


@pytest.mark.parametrize('lost', [False, True])
def test_video_write_preserves_ambiguous_submission(meme, browser, monkeypatch, memory_ledger, lost):
    def page(url, mode='read'):
        browser.append(mode)
        if mode == 'meme_open': return {**meme, 'state': 'menu_opened'}
        if mode == 'meme_confirm': return {} if lost else {**meme, 'state': 'submitted'}
        return {**meme, 'state': 'reposted' if 'meme_confirm' in browser else 'ready'}
    monkeypatch.setattr(repost_page, 'read', page)
    assert tc.repost_meme(meme['url']) is (tc.WriteOutcome.UNCONFIRMED if lost else tc.WriteOutcome.SHIPPED)
    assert browser.count('meme_confirm') == 1
    assert repost_store.entries()[x_urls.status_id(meme['url'])]['status'] == ('pending' if lost else 'shipped')
    assert len(memory_ledger.rows) == (0 if lost else 1)
    assert tc.repost_meme(meme['url']) is tc.WriteOutcome.REFUSED


@pytest.mark.parametrize('changed', [dict(text='My AI agent now writes production code.'), dict(media_id='999999'), dict(has_video=False)])
def test_video_identity_and_source_rechecked_before_confirmation(meme, browser, monkeypatch, changed):
    def page(url, mode='read'):
        browser.append(mode)
        if mode == 'meme_open': return {**meme, 'state': 'menu_opened'}
        assert mode != 'meme_confirm'
        return {**meme, **(changed if 'meme_open' in browser else {})}
    monkeypatch.setattr(repost_page, 'read', page)
    assert tc.repost_meme(meme['url']) is tc.WriteOutcome.REFUSED
    assert 'meme_open' in browser and not repost_store.contains(meme['url'])


@pytest.mark.parametrize('change', [dict(funny=False), dict(needs_unavailable_audio=True), dict(all_samples_reviewed=False), dict(safe_to_amplify=False), {}])
def test_only_visually_supported_funny_video_review_can_repost(meme, monkeypatch, change):
    store.offer([meme])
    observed = evidence(meme)
    observed['verdict'].update(change)
    monkeypatch.setattr(tc, 'read_meme_post', lambda _: meme)
    monkeypatch.setattr(video, 'inspect', lambda _: observed)
    sent=[]
    monkeypatch.setattr(tc, 'repost_meme', lambda url: sent.append(url))
    job.run_meme_repost_cycle()
    assert len(sent) == (0 if change else 1)


def test_uninspected_text_approval_cannot_unlock_video(meme):
    with pytest.raises(ValueError, match='uninspected'):
        store.review(meme['url'], meme['text'], True, 'funny caption', 9)


def test_light_visual_humor_does_not_need_an_exceptional_score(meme):
    observed = evidence(meme)
    observed['verdict']['humor_score'] = 5
    assert video.valid(observed, meme['url'], meme['text'], meme['media_id'])


@pytest.mark.parametrize('broken', ['source', 'media', 'frames', 'timestamps', 'observations'])
def test_approval_requires_matching_source_and_complete_visual_evidence(meme, broken):
    observed = evidence(meme)
    if broken == 'source': observed['source_hash'] = 'f' * 64
    if broken == 'media': observed['media_id'] = 'other'
    if broken == 'frames': observed['frames'].pop()
    if broken == 'timestamps': observed['frames'][1]['at'] = -1
    if broken == 'observations': observed['verdict']['observations'] = [dict(at=.5)] * 3
    assert not video.valid(observed, meme['url'], meme['text'], meme['media_id'])


def test_legacy_text_review_stays_readable_but_cannot_authorize_video(meme):
    store.STATE.write({x_urls.status_id(meme['url']): dict(url=meme['url'], source_text=meme['text'],
        source_hash=store.digest(meme['text']), approved=True, humor_score=9,
        at=active_hours.now_local().isoformat(), reason='old text review')})
    assert store.entries()
    assert not store.approved(meme['url'])
    assert not ag.can_post(ag.MEME_REPOST, target=meme['url'])[0]


def test_recent_reply_prioritizes_video_without_browser_work(meme):
    popular = {**meme, 'url': fresh('other', n=1), 'likes': 1000000}
    store.offer([meme, popular])
    store.note_reply(meme['url'])
    assert store.next_candidate()['url'] == meme['url']


def test_last_confirmed_reply_is_checked_after_restart(meme, monkeypatch, tmp_path):
    log = tmp_path / 'engagement.csv'
    with log.open('w') as handle:
        csv.writer(handle).writerows([['date', 'reply', 'Mr Huang', meme['url']]])
    monkeypatch.setattr(config, 'ENGAGEMENT_LOG_FILE', log)
    monkeypatch.setattr(store, '_seeded', False)
    assert store.next_candidate()['url'] == meme['url']
    store.defer(meme['url'])
    assert store.next_candidate() is None
