import json
import shutil
import subprocess

import pytest

from src.core import account
from src.x import quote_page, safari
from tests.helpers import fresh


def composer_page(**options):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for DOM guard tests")
    setup = r"""
const opt = __OPTIONS__, counts = {submit:0,focus:0};
const location = {hostname:'x.com',origin:'https://x.com'};
const fields = [{innerText: opt.text ?? 'A useful update.', contains:()=>false, focus:()=>counts.focus++, getClientRects:()=>[1]}];
if (opt.fields === 2) fields.push(fields[0]);
const button = {getClientRects:()=>[1],getAttribute:()=>null,click:()=>counts.submit++};
const area = {getClientRects:()=>[1],contains:()=>false,querySelectorAll:s=>
  s.includes('tweetTextarea') ? fields : s.includes('/status/') ? [{href:opt.source || 'https://x.com/builder/status/123'}] : [button]};
const wrapper = {getClientRects:()=>[1], contains:d=>d===area};
const other = {getClientRects:()=>[1],contains:()=>false};
const document = {querySelector:()=>({getAttribute:()=>'/'+(opt.owner || 'ownbot')}),
  querySelectorAll:()=>opt.dialogs===2 ? [area,other] : opt.nested ? [wrapper,area] : [area]};
""".replace("__OPTIONS__", json.dumps(options))
    js = setup + "\nconst result = " + quote_page.COMPOSER + "(" + ",".join(json.dumps(v) for v in (
        "https://x.com/builder/status/123", "A useful update.", "ownbot", options.get("mode", "submit"))) + ");\nconsole.log(JSON.stringify({result:JSON.parse(result),counts}));"
    return json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout)


@pytest.mark.parametrize("wrong", [dict(owner="other"), dict(source="https://x.com/other/status/123"),
    dict(source="https://evil.example/builder/status/123"),
    dict(source="https://x.com/builder/status/124"), dict(text="Different words"), dict(dialogs=2), dict(fields=2)])
def test_quote_composer_never_clicks_wrong_owner_source_text_or_ambiguous_dialog(wrong):
    result = composer_page(**wrong)
    assert result["result"] == {"ready": False}
    assert result["counts"]["submit"] == 0


def test_nested_wrapper_is_one_quote_dialog_and_clicks_once():
    result = composer_page(nested=True)
    assert result["result"] == {"ready": True}
    assert result["counts"] == {"submit": 1, "focus": 0}


def test_focus_does_not_replace_an_existing_draft():
    assert composer_page(mode="focus")["counts"]["focus"] == 0
    assert composer_page(mode="focus", text="")["counts"] == {"submit": 0, "focus": 1}


@pytest.mark.parametrize("wrong", ["author", "text", "source", "old", "ambiguous"])
def test_receipt_requires_exact_own_body_source_and_submission_time(monkeypatch, wrong):
    source = fresh("builder")
    own = fresh(account.current().handle, minutes=0)
    since = quote_page.time.time()
    row = dict(url=own, text="A useful update.", sources=[source])
    if wrong == "author": row["url"] = fresh("other", minutes=0)
    if wrong == "text": row["text"] = "Different text."
    if wrong == "source": row["sources"] = [fresh("other")]
    if wrong == "old": row["url"] = fresh(account.current().handle, minutes=2)
    rows = [row]
    if wrong == "ambiguous": rows.append({**row,"url":fresh(account.current().handle, minutes=0, n=1)})
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: json.dumps(rows))
    monkeypatch.setattr(quote_page.time, "sleep", lambda *_: None)
    assert quote_page.receipt(source, "A useful update.", since) == ""
