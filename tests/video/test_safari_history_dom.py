"""Quoted timestamps must never replace a profile post's own identity."""
import json
import shutil
import subprocess

import pytest

from src.x.safari_video import _POSTS


def test_quote_before_root_timestamp_keeps_root_post_and_visible_quote_video():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for page JavaScript")
    setup = r'''
const article = {};
const element = (values, quoted=false) => ({...values, closest: selector =>
  selector.startsWith('article') ? article : quoted ? {} : null});
const link = element({getAttribute: () => '/ExampleBot/status/1234567890123456789'});
const rootTime = element({dateTime:'2026-11-01T12:00:00Z'});
rootTime.closest = selector => selector.startsWith('a[') ? link : selector.startsWith('article') ? article : null;
const quoteTime = element({dateTime:'2025-01-01T12:00:00Z'}, true);
const user = element({getAttribute: () => '/ExampleBot'});
const text = element({innerText:'Our original post'});
const quoteText = element({innerText:'Quoted content'}, true);
const video = element({currentSrc:'blob:fixture', duration:20}, true);
article.querySelectorAll = selector => ({
  'time[datetime]':[quoteTime,rootTime],
  '[data-testid="User-Name"] a[href]':[element({getAttribute:()=>'/Other'},true),user],
  '[data-testid="tweetText"]':[quoteText,text]
}[selector] || []);
article.querySelector = selector => selector === 'video' ? video : null;
global.location={hostname:'x.com'};
global.window={scrollY:0,innerHeight:1000};
global.document={documentElement:{scrollHeight:1000},querySelector:()=>null,
  querySelectorAll: selector => selector.startsWith('article') ? [article] : []};
'''
    result = subprocess.run([node, "-e", setup + "\nconsole.log(" + _POSTS + ")"],
                            capture_output=True, text=True, check=True, timeout=10)
    post = json.loads(result.stdout)["posts"][0]
    assert post["id"] == "1234567890123456789"
    assert post["text"] == "Our original post"
    assert post["created_at"] == "2026-11-01T12:00:00Z"
    assert post["video"] is True
