from datetime import timedelta

from src.core import account
from src.x import reply_metrics as metrics
from tests.core.test_reply_feedback import NOW, url
from tests.helpers import clock


def test_capture_needs_one_recent_exact_own_reply(monkeypatch):
    clock(monkeypatch, NOW)
    own = url(NOW - timedelta(seconds=1), handle=account.current().handle)
    parent = url(NOW - timedelta(minutes=20))
    rows = [{"url": own, "text": "A specific reaction."},
            {"url": parent, "text": "A specific reaction."}]
    monkeypatch.setattr(metrics, "read_visible", lambda: rows)
    assert metrics.capture("A specific reaction.", since=NOW - timedelta(seconds=3), parent=parent) == own
    assert metrics.capture("Different reaction.", since=NOW - timedelta(seconds=3), parent=parent) == ""
    rows.append({"url": url(handle=account.current().handle, extra=1), "text": "A specific reaction."})
    assert metrics.capture("A specific reaction.", since=NOW - timedelta(seconds=3), parent=parent) == ""


def test_old_identical_text_is_not_a_new_receipt(monkeypatch):
    clock(monkeypatch, NOW)
    old = url(NOW - timedelta(hours=1), handle=account.current().handle)
    monkeypatch.setattr(metrics, "read_visible", lambda: [{"url": old, "text": "A specific reaction."}])
    assert metrics.capture("A specific reaction.", since=NOW - timedelta(seconds=3), parent=url()) == ""


def test_observe_refuses_foreign_urls_and_reads_the_exact_own_status(monkeypatch):
    from src.x import safari
    clock(monkeypatch, NOW)
    own = url(handle=account.current().handle)
    opened, closed = [], []
    monkeypatch.setattr(safari, "open_url", lambda u: opened.append(u) or True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: closed.append(True))
    monkeypatch.setattr(metrics.time, "sleep", lambda _: None)
    monkeypatch.setattr(metrics, "read_visible", lambda: [{"url": url(), "likes": 999, "views": 9999},
                                                         {"url": own, "likes": 0, "views": None}])
    assert metrics.observe(url()) is None
    assert metrics.observe(own.replace("x.com", "evil.com")) is None
    assert not opened
    assert metrics.observe(own) == {"url": own, "likes": 0, "views": None}
    assert opened == [own] and closed == [True]


def test_page_counters_distinguish_missing_values_from_zero():
    import json, shutil, subprocess
    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("node is needed to exercise page JavaScript")
    setup = r'''
      const location = {hostname:'x.com'};
      const article = {};
      const element = label => ({getAttribute:()=>label, closest:()=>article});
      article.querySelector = sel => {
        if (sel.startsWith('time')) return {closest:()=>element('/ownbot/status/123')};
        if (sel.includes('tweetText')) return {textContent:'Specific reply'};
        if (sel.includes('User-Name')) return element('/ownbot');
        if (sel.includes('unlike')) return element('0 Likes. Like');
        if (sel.includes('analytics')) return null;
        return null;
      };
      const document = {querySelectorAll:()=>[article]};
    '''
    result = subprocess.run([node,"-e",setup + '\nconsole.log(' + metrics._VISIBLE + ');'],capture_output=True,text=True,check=True)
    row = json.loads(result.stdout)[0]
    assert row["likes"] == 0 and row["views"] is None
    setup = setup.replace("if (sel.includes('analytics')) return null;", "if (sel.includes('analytics')) return element('1.2K Views');")
    result = subprocess.run([node,"-e",setup + '\nconsole.log(' + metrics._VISIBLE + ');'],capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)[0]["views"] == 1200
