"""News intent dialogs may coexist with the home-page composer."""
import json
import shutil
import subprocess

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
