"""News intent dialogs may coexist with the home-page composer."""
import json
import shutil
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.core import account
from src.x import news_page


@pytest.mark.parametrize("mode,allowed", [
    ("home_behind_dialog", True), ("nested_dialog", True), ("inline", True), ("wrong_text", False),
    ("wrong_owner", False), ("two_dialogs", False), ("two_fields", False),
    ("disabled", False),
])
def test_only_the_unique_matching_composer_can_submit(monkeypatch, mode, allowed):
    node = shutil.which("node")
    if not node:
        pytest.skip("DOM fixture needs Node")
    text = "A verified SI announcement.\n\nhttps://example.org/source"
    setup = "const mode=" + json.dumps(mode) + ", text=" + json.dumps(text) + ", handle=" + json.dumps(account.current().handle) + ";" + r"""
      let clicks = 0;
      const visible = () => [1];
      const button = {getClientRects:visible, disabled:mode==='disabled', getAttribute:()=>null, click:()=>clicks++};
      const field = {getClientRects:visible, innerText:mode==='wrong_text'?'Unreviewed text':text};
      const background = {getClientRects:visible, innerText:''};
      const area = {getClientRects:visible, contains:()=>false, querySelectorAll:s=>s.includes('tweetTextarea') ?
        (mode==='two_fields' ? [field,background] : [field]) : [button]};
      const outer = {getClientRects:visible, contains:d=>d===area, querySelectorAll:area.querySelectorAll};
      const main = {querySelectorAll:s=>s.includes('tweetTextarea') ? [background] : [button]};
      const location = {hostname:'x.com'};
      const document = {
        querySelector:s=>s.includes('Profile_Link') ? {getAttribute:()=>'/'+(mode==='wrong_owner'?'someone_else':handle)} : (mode==='inline'?area:main),
        querySelectorAll:s=>s==='[role="dialog"]' ? (mode==='inline'?[]:mode==='two_dialogs'?[area,area]:mode==='nested_dialog'?[outer,area]:[area]) : [background,field]
      };
    """
    observed = []

    def read(js):
        program = setup + "\nconst result=" + js + "; console.log(JSON.stringify({result:JSON.parse(result),clicks}));"
        response = subprocess.run([node], input=program, text=True, capture_output=True, check=True, timeout=10)
        result = json.loads(response.stdout)
        observed.append(result)
        return result["result"]

    monkeypatch.setattr(news_page, "_read", read)
    monkeypatch.setattr(news_page, "require_active", lambda: None)
    assert news_page.composer(text, click=True) is allowed
    assert observed[0]["clicks"] == int(allowed)


@pytest.mark.parametrize("change,matched", [
    ("none", True), ("wrong_source", False), ("changed_text", False),
    ("wrong_author", False), ("old_status", False), ("no_link", False),
])
def test_link_card_receipt_needs_exact_body_author_time_and_source(monkeypatch, change, matched):
    source = "https://example.org/source"
    text = "A verified announcement.\n\nSI BANGER.\n\n" + source
    handle = account.current().handle
    url = "https://x.com/" + ("someone_else" if change == "wrong_author" else handle) + "/status/123"
    row = {"url": url, "text": "Changed" if change == "changed_text" else text.removesuffix(source),
           "links": [] if change == "no_link" else ["https://t.co/observed"]}
    monkeypatch.setattr(news_page, "_read", lambda js: [row])
    monkeypatch.setattr(news_page, "require_active", lambda: None)
    monkeypatch.setattr(news_page.time, "time", lambda: 1010)
    monkeypatch.setattr(news_page.time, "sleep", lambda _: None)
    monkeypatch.setattr(news_page.safari, "_run_js", lambda *a, **k: "")
    monkeypatch.setattr(news_page.x_urls, "posted_at", lambda _: datetime.fromtimestamp(900 if change == "old_status" else 1001, timezone.utc))
    resolved = []
    def check(link, expected, store, cfg):
        resolved.append(link)
        assert expected == source
        return change != "wrong_source"
    monkeypatch.setattr(news_page, "_shortlink_matches", check)
    assert news_page.receipt(text, source, 1000) == (url if matched else "")
    assert len(resolved) <= 1  # failed observations are not fetched on every poll


@pytest.mark.parametrize("location,matched", [
    ("https://example.org/source", True), ("https://example.org/another", False),
])
def test_shortlink_read_is_charged_head_only_and_never_follows(monkeypatch, location, matched):
    from src.video import security
    requests, charges = [], []
    class Connection:
        def __init__(self, host, timeout):
            assert host == "t.co" and timeout == 3
        def request(self, method, path):
            requests.append((method, path))
        def getresponse(self):
            return SimpleNamespace(status=301, getheader=lambda _: location)
        def close(self):
            pass
    monkeypatch.setattr(security, "_PinnedHTTPS", Connection)
    store = SimpleNamespace(charge=lambda *a: charges.append(a))
    cfg = SimpleNamespace(requests_per_day=100)
    assert news_page._shortlink_matches("https://t.co/observed", "https://example.org/source", store, cfg) is matched
    assert requests == [("HEAD", "/observed")] and len(charges) == 1
    assert not news_page._shortlink_matches("https://127.0.0.1/observed", location, store, cfg)
    assert len(requests) == len(charges) == 1
