from dataclasses import replace
import json
import os
import sqlite3

import pytest

from src.video import operations, publisher, workers
from src.video.security import AccessError, sha256
from src.video.store import Store, SCHEMA
from src.x import safari, safari_video as browser, twitter_client
from src.x.confirmed_write import WriteOutcome
from tests.helpers import clock


def test_upload_processing_allowance_is_bounded_and_does_not_expand_slot_grace(video_cfg):
    longer = replace(video_cfg, browser_upload_seconds=180)
    assert longer.grace_seconds == video_cfg.grace_seconds
    assert longer.lease_seconds == video_cfg.lease_seconds
    with pytest.raises(ValueError, match="10..180"):
        replace(video_cfg, browser_upload_seconds=181)


@pytest.mark.parametrize("priority, expected_wait", [(2, 5), (1, 60), (0, 60)])
def test_busy_video_read_waits_for_its_priority_then_defers(monkeypatch, priority, expected_wait):
    from contextlib import nullcontext
    from src.core import work_priority
    from src.video.security import Deferred
    monkeypatch.setattr(browser, "publisher_session", lambda: nullcontext())
    monkeypatch.setattr(browser, "require_active", lambda: None)
    waits = []
    monkeypatch.setattr(safari._safari_lock._lock, "acquire", lambda timeout: waits.append(timeout) or False)
    monkeypatch.setattr(safari._safari_lock._lock, "release", lambda: pytest.fail("unowned lock released"))
    with work_priority.scope(priority), pytest.raises(Deferred, match="Safari busy"), browser.browser_session():
        pytest.fail("read began without the browser")
    assert waits == [expected_wait]


def test_required_video_read_rechecks_active_hours_after_queue_and_releases(monkeypatch):
    from contextlib import nullcontext
    from src.core import work_priority
    from src.guards.active_hours import OutsideActiveHours
    monkeypatch.setattr(browser, "publisher_session", lambda: nullcontext())
    checks, released = [], []
    def active():
        checks.append(True)
        if len(checks) == 2:
            raise OutsideActiveHours("bedtime during wait")
    monkeypatch.setattr(browser, "require_active", active)
    monkeypatch.setattr(safari._safari_lock._lock, "acquire", lambda timeout: True)
    monkeypatch.setattr(safari._safari_lock._lock, "release", lambda: released.append(True))
    with work_priority.scope(work_priority.REPLY), pytest.raises(OutsideActiveHours), browser.browser_session():
        pytest.fail("read began after bedtime")
    assert released == [True]


def test_receipt_reads_own_profile_when_success_toast_has_no_link(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    monkeypatch.setattr(browser.account, "current", lambda: SimpleNamespace(handle="example"))
    monkeypatch.setattr(browser, "require_active", lambda: None)
    monkeypatch.setattr(browser.time, "sleep", lambda *_: None)
    monkeypatch.setattr(browser.time, "time", lambda: 1000)
    monkeypatch.setattr(browser.x_urls, "posted_at", lambda _: datetime.fromtimestamp(999, timezone.utc))
    snapshots = iter([{}] * 4 + [{"posts": [{"id": "123", "author": "example", "text": "BANGER 😂\n\nDance break 🕺",
                                           "video": True, "url": "https://x.com/example/status/123"}]}])
    monkeypatch.setattr(browser, "_json", lambda *_: next(snapshots))
    scripts = []
    monkeypatch.setattr(safari, "_run_js", lambda js, *_: scripts.append(js))
    page = object.__new__(browser.Composer)
    page.caption = "BANGER 😂\n\nDance break 🕺"
    assert page.receipt(998) == "123"
    assert len(scripts) == 1 and "https://x.com/example" in scripts[0]


def test_blob_video_fingerprints_visible_frames_without_api(video_store, browser_cfg, monkeypatch):
    import base64
    from contextlib import nullcontext
    import io
    from PIL import Image, ImageDraw
    images = []
    for x in (2, 14, 28, 44):
        image = Image.new("RGB", (64, 64), "black")
        ImageDraw.Draw(image).rectangle((x, 12, x + 10, 50), fill="white")
        data = io.BytesIO()
        image.save(data, format="PNG")
        images.append("data:image/png;base64," + base64.b64encode(data.getvalue()).decode())
    monkeypatch.setattr(browser, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda *a: True)
    closed = []
    monkeypatch.setattr(safari, "close_front_tab", lambda: closed.append(True))
    def page(js, *a):
        if "png:c.toDataURL" in js:
            return {"at": 4 - len(images) + .5, "png": images.pop(0)}
        return {"duration": 4, "ready_state": 2}
    monkeypatch.setattr(browser, "_json", page)
    client = browser.SafariVideoClient(video_store, browser_cfg)
    item = {"post_url": "https://x.com/example/status/123"}
    result = client.fingerprint(item)
    assert len(result["visual"]) == 4 and result["audio"] == []
    assert "visible browser" in result["method"] and closed == [True]
    assert client.fingerprint(item) == result and closed == [True]


def test_unloaded_history_media_requests_metadata_but_stays_unchecked_on_failure(video_store, browser_cfg, monkeypatch):
    from contextlib import nullcontext
    monkeypatch.setattr(browser, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda *a: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    clock = [0]
    monkeypatch.setattr(browser.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(browser.time, "sleep", lambda *_: clock.__setitem__(0, 30))
    scripts = []
    info = {"duration": None, "article": True, "video": False, "ready_state": None, "error": None}
    def page(js):
        scripts.append(js)
        return info
    monkeypatch.setattr(browser, "_json", page)
    client = browser.SafariVideoClient(video_store, browser_cfg)
    with pytest.raises(AccessError, match="duration unavailable"):
        client.fingerprint({"post_url": "https://x.com/example/status/123"})
    assert len(scripts) == 1
    assert "v.preload='auto';v.muted=true;" in scripts[0] and "v.play().catch" in scripts[0]
    assert "click(" not in scripts[0]
    assert video_store.meta("browser_video_access:123")["article"] is True
    assert not video_store.meta("browser_fingerprint:123")


def test_metadata_only_video_requests_muted_decoding_and_saves_why_it_waits(video_store, browser_cfg, monkeypatch):
    from contextlib import nullcontext
    from src.video.security import Deferred
    monkeypatch.setattr(browser, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda *a: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    clock = [0]
    monkeypatch.setattr(browser.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(browser.time, "sleep", lambda *_: clock.__setitem__(0, 30))
    scripts = []
    def page(js):
        scripts.append(js)
        return {"duration": 4, "ready_state": 1, "paused": True, "network_state": 2, "playback_error": "NotAllowedError"}
    monkeypatch.setattr(browser, "_json", page)
    client = browser.SafariVideoClient(video_store, browser_cfg)
    with pytest.raises(Deferred, match="decoded frames"):
        client.fingerprint({"post_url": "https://x.com/example/status/123"})
    assert "v.readyState<2" in scripts[0] and "loading('metadata')" in scripts[0]
    status = video_store.meta("browser_video_access:123")
    assert status["phase"] == "frame_loading" and status["ready_state"] == 1
    assert status["playback_error"] == "NotAllowedError"
    assert not video_store.meta("browser_fingerprint:123")
    # Execute the browser program: HAVE_METADATA must actually start muted
    # decoding, rather than merely containing a play() branch for readyState=0.
    import shutil
    import subprocess
    if shutil.which("node"):
        setup = """
const video={error:null,readyState:1,duration:4,currentTime:0,dataset:{},muted:false,paused:true,plays:0,
  scrollIntoView(){},
  play(){this.plays++;this.readyState=2;this.paused=false;return Promise.resolve();}};
const link={getAttribute:()=>'/example/status/123'};
const article={querySelectorAll:()=>[stamp],querySelector:()=>video};
const stamp={closest:s=>s==='article'?article:s==='a'?link:null};
const location={hostname:'x.com',pathname:'/example/status/123'};
const document={querySelectorAll:s=>s.startsWith('article[data-testid')?[article]:[],querySelector:()=>null};
"""
        program = setup + "const info=JSON.parse(" + scripts[0] + ");console.log(JSON.stringify({info,muted:video.muted,plays:video.plays}));"
        observed = json.loads(subprocess.run(["node", "-e", program], check=True, capture_output=True, text=True, timeout=10).stdout)
        assert observed["plays"] == 1 and observed["muted"] is True and observed["info"]["ready_state"] == 2


def test_first_seek_timeout_saves_empty_progress_and_bounded_player_diagnostics(video_store, browser_cfg, monkeypatch):
    from contextlib import nullcontext
    from src.video.security import Deferred
    monkeypatch.setattr(browser, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda *a: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    clock = [0]
    monkeypatch.setattr(browser.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(browser.time, "sleep", lambda *_: clock.__setitem__(0, 30))
    scripts = []
    def page(js):
        scripts.append(js)
        if "png:c.toDataURL" in js:
            return {"ready_state": 1, "seeking": True, "current_time": .5, "network_state": 2}
        return {"duration": 4, "ready_state": 2}
    monkeypatch.setattr(browser, "_json", page)
    client = browser.SafariVideoClient(video_store, browser_cfg)
    with pytest.raises(Deferred, match="fingerprint is pending"):
        client.fingerprint({"post_url": "https://x.com/example/status/123"})
    assert video_store.meta("browser_fingerprint_pending:123")["visual"] == []
    status = video_store.meta("browser_video_access:123")
    assert status["phase"] == "seek" and status["sample_index"] == 0 and status["samples_saved"] == 0
    assert status["ready_state"] == 1 and status["requested_at"] == .5
    assert "v.dataset.botSeekLoad='loading'" in scripts[-1]
    assert not video_store.meta("browser_fingerprint:123")


@pytest.mark.parametrize("phase", ["metadata", "seek"])
def test_native_player_recovers_after_x_pauses_the_first_play_request(
        video_store, browser_cfg, monkeypatch, phase):
    """Execute the actual page programs, including an overshoot and exact reseek."""
    from contextlib import nullcontext
    import shutil
    import subprocess
    from src.video.security import Deferred
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for page JavaScript")
    monkeypatch.setattr(browser, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda *a: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    clock = [0]
    monkeypatch.setattr(browser.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(browser.time, "sleep", lambda *_: clock.__setitem__(0, 30))
    scripts = []
    def page(js):
        scripts.append(js)
        return {"ready_state": 1, "seeking": True} if "png:c.toDataURL" in js else {"duration": 4, "ready_state": 2}
    monkeypatch.setattr(browser, "_json", page)
    with pytest.raises(Deferred):
        browser.SafariVideoClient(video_store, browser_cfg).fingerprint({"post_url": "https://x.com/example/status/123"})
    program = scripts[0] if phase == "metadata" else scripts[-1]
    setup = r"""
let now=0, drawn=[], scrolls=0;
const performance={now:()=>now};
const video={error:null,readyState:1,duration:4,_at:.5,dataset:{},muted:false,paused:true,seeking:true,plays:0,
  buffered:{length:1,start:()=>0,end:()=>4},seekable:{length:1,start:()=>0,end:()=>4},
  scrollIntoView(){if(!this.muted)throw Error('unmuted scroll');scrolls++;},
  get currentTime(){return this._at;},
  set currentTime(at){this._at=at;this.seeking=this.readyState<2;},
  pause(){this.paused=true;},
  play(){if(!this.muted)throw Error('unmuted play');this.plays++;
    if(this.plays===1){this.paused=true;return Promise.resolve();}
    this.paused=false;this.readyState=4;this.seeking=false;this._at=.75;return Promise.resolve();}};
const link={getAttribute:()=>'/example/status/123'};
const article={querySelectorAll:()=>[stamp],querySelector:()=>video};
const stamp={closest:s=>s==='article'?article:s==='a'?link:null};
const location={hostname:'x.com',pathname:'/example/status/123'};
const document={visibilityState:'visible',querySelectorAll:s=>s.startsWith('article[data-testid')?[article]:[],
  querySelector:()=>null,createElement:()=>({getContext:()=>({drawImage:v=>drawn.push(v.currentTime)}),toDataURL:()=> 'fixture'})};
"""
    run = "const run=()=>JSON.parse(" + program + ");"
    steps = "const states=[run()];now=500;states.push(run());now=1000;states.push(run());now=1001;states.push(run());"
    output = subprocess.run([node, "-e", setup + run + steps +
        "console.log(JSON.stringify({states,plays:video.plays,drawn,scrolls}));"],
        check=True, capture_output=True, text=True, timeout=10)
    result = json.loads(output.stdout)
    assert result["plays"] == 2 and result["scrolls"] == 1
    assert result["states"][0]["ready_state"] == 1 and result["states"][1]["play_attempts"] == 1
    assert result["states"][0]["buffered"] == [[0, 4]]
    if phase == "seek":
        assert not any(row.get("png") for row in result["states"][:3])
        assert result["states"][3]["at"] == .5 and result["drawn"] == [.5]
    else:
        assert result["states"][2]["ready_state"] == 4 and result["drawn"] == []


def test_stalled_native_playback_retries_are_bounded_and_never_fake_frames():
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for page JavaScript")
    setup = r"""
let now=0;const performance={now:()=>now};const document={visibilityState:'visible'};
const v={error:null,paused:true,readyState:1,dataset:{},plays:0,scrollIntoView(){},
  play(){this.plays++;return Promise.resolve();}};
"""
    steps = r"""
for(now=0;now<25000;now+=80)loading('seek:1');
const first=playerState();
now=25000;loading('seek:2');const second=playerState();
v.error={code:4};now=27000;loading('seek:3');
console.log(JSON.stringify({first,second,plays:v.plays,final:playerState()}));
"""
    result = json.loads(subprocess.run([node, "-e", setup + browser._FRAME_LOADING + steps],
        check=True, capture_output=True, text=True, timeout=10).stdout)
    assert result["first"]["play_attempts"] == 6 and result["first"]["ready_state"] == 1
    assert result["second"]["play_attempts"] == result["plays"] == 7
    assert result["final"]["media_error"] == 4


def test_cors_protected_native_video_remains_unchecked(video_store, browser_cfg, monkeypatch):
    from contextlib import nullcontext
    from src.video import reconcile
    monkeypatch.setattr(browser, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda *a: True)
    closed = []
    monkeypatch.setattr(safari, "close_front_tab", lambda: closed.append(True))
    monkeypatch.setattr(browser, "_json", lambda js, *a: {"error": "frame access denied"} if "png:c.toDataURL" in js else {"duration": 4, "ready_state": 2})
    client = browser.SafariVideoClient(video_store, browser_cfg)
    with pytest.raises(AccessError, match="origin policy"):
        reconcile.media_fingerprint({"type": "video", "post_url": "https://x.com/example/status/123"},
                                    video_store, browser_cfg, 0, client=client)
    assert closed == [True] and not video_store.meta("browser_fingerprint:123")


def test_long_browser_fingerprint_resumes_without_claiming_partial_success(video_store, browser_cfg, monkeypatch):
    import base64
    from contextlib import nullcontext
    import io
    from PIL import Image, ImageDraw
    from src.video.security import Deferred
    monkeypatch.setattr(browser, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda *a: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    captured = []
    def page(js, *a):
        if "png:c.toDataURL" not in js:
            return {"duration": 12, "ready_state": 2}
        x = len(captured) * 4
        image = Image.new("RGB", (64, 64), "black")
        ImageDraw.Draw(image).rectangle((x, 10, x + 12, 54), fill="white")
        data = io.BytesIO(); image.save(data, format="PNG")
        captured.append(x)
        return {"at": len(captured) - .5, "png": "data:image/png;base64," + base64.b64encode(data.getvalue()).decode()}
    monkeypatch.setattr(browser, "_json", page)
    client = browser.SafariVideoClient(video_store, browser_cfg)
    item = {"post_url": "https://x.com/example/status/123"}
    with pytest.raises(Deferred):
        client.fingerprint(item)
    assert not video_store.meta("browser_fingerprint:123")
    assert len(video_store.meta("browser_fingerprint_pending:123")["visual"]) == 8
    assert len(client.fingerprint(item)["visual"]) == 12
    assert len(captured) == 12


@pytest.mark.parametrize("case", ["gap", "no_left", "no_right", "already_buffered", "outside_cell", "undecoded", "cors"])
def test_native_gap_fallback_requires_buffered_same_cell_and_actual_decoded_canvas(case):
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for page JavaScript")
    requested, start, end = 62.5 / 60, 0, 62.5 / 30
    buffered = [[0, 1 / 60], [.233333, .25], [3.001667, 14.975]]
    if case == "no_left":
        buffered = [[3, 10]]
    elif case == "no_right":
        buffered = [[0, .25]]
    elif case == "already_buffered":
        buffered = [[0, 10]]
    elif case == "outside_cell":
        requested, start, end, buffered = 2, 1, 3, [[0, .3], [3, 10]]
    setup = "const intervals=" + json.dumps(buffered) + ";const mode=" + json.dumps(case) + ";const requestedTime=" + str(requested) + ";" + r"""
let now=0, drawn=[], seeks=[];const performance={now:()=>now};
const video={readyState:1,seeking:true,paused:true,error:null,dataset:{},_at:requestedTime,
  buffered:{length:intervals.length,start:i=>intervals[i][0],end:i=>intervals[i][1]},
  scrollIntoView(){},pause(){this.paused=true;},play(){return Promise.resolve();},
  get currentTime(){return this._at;},set currentTime(value){this._at=value;seeks.push(value);
    const available=intervals.some(r=>r[0]<=value && value<r[1]);
    this.readyState=available && mode!=='undecoded'?2:1;this.seeking=this.readyState<2;}};
const document={visibilityState:'visible',createElement:()=>({getContext:()=>({drawImage:v=>{
  if(v.readyState<2 || v.seeking)throw Error('undecoded frame');drawn.push(v.currentTime);
}}),toDataURL:()=>{if(mode==='cors')throw Error('SecurityError');return 'fixture';}})};
"""
    script = browser._sample_frame_script("const v=video;", requested, start, end)
    run = "const run=()=>JSON.parse(" + script + ");"
    steps = "const states=[run()];now=1999;states.push(run());now=2000;states.push(run());now=2001;states.push(run());"
    result = json.loads(subprocess.run([node, "-e", setup + run + steps +
        "console.log(JSON.stringify({states,drawn,seeks}));"], capture_output=True, text=True, check=True, timeout=10).stdout)
    assert not any(state.get("png") for state in result["states"][:3])
    if case in ("gap", "undecoded", "cors"):
        assert result["seeks"] == [pytest.approx((.233333 + .25) / 2)]
        assert result["states"][2]["gap"]["previous_end"] == .25
        assert result["states"][2]["gap"]["next_start"] == 3.001667
        assert result["states"][2]["sample_target"] != requested
        if case == "gap":
            frame = result["states"][3]
            assert frame["png"] == "fixture" and result["drawn"] == [frame["at"]]
            evidence = browser._sample_evidence(frame, requested, start, end)
            assert evidence["actual_at"] != evidence["requested_at"]
            assert start <= evidence["actual_at"] < end
        elif case == "cors":
            assert result["states"][3] == {"error": "frame access denied"}
        else:
            assert not result["drawn"] and not result["states"][3].get("png")
    else:
        assert result["seeks"] == [] and result["drawn"] == []
        assert all(state["gap"] is None for state in result["states"])


def test_gap_sampling_persists_real_times_and_requires_all_thirty_cells(video_store, browser_cfg, monkeypatch):
    import base64
    from contextlib import nullcontext
    import io
    from PIL import Image, ImageDraw
    from src.video.security import Deferred
    monkeypatch.setattr(browser, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda *a: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    sample = []
    original_script = browser._sample_frame_script
    def script(select, requested, start, end):
        sample[:] = [requested, start, end]
        return original_script(select, requested, start, end)
    monkeypatch.setattr(browser, "_sample_frame_script", script)
    captured = []
    def page(js, *args):
        if "png:c.toDataURL" not in js:
            return {"duration": 62.5, "ready_state": 2}
        requested, start, end = sample
        image = Image.new("RGB", (64, 64), "black")
        x = len(captured) * 7 % 50
        ImageDraw.Draw(image).rectangle((x, 10, x + 10, 54), fill="white")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        frame = {"at": requested, "sample_target": requested,
                 "png": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()}
        if not captured:
            frame.update(at=.2416665, sample_target=.2416665,
                gap={"requested_at": requested, "target": .2416665, "previous_end": .25,
                     "next_start": 3.001667, "buffered_interval": [.233333, .25]})
        captured.append((start, end))
        return frame
    monkeypatch.setattr(browser, "_json", page)
    client = browser.SafariVideoClient(video_store, browser_cfg)
    item = {"post_url": "https://x.com/example/status/123"}
    for batch in range(3):
        with pytest.raises(Deferred):
            client.fingerprint(item)
        assert video_store.meta("browser_fingerprint:123") is None
        saved = video_store.meta("browser_fingerprint_pending:123")
        assert len(saved["visual"]) == len(saved["samples"]) == (batch + 1) * 8
        assert saved["samples"][0]["actual_at"] == .2416665
        assert saved["samples"][0]["requested_at"] == 62.5 / 60
    result = client.fingerprint(item)
    assert len(result["samples"]) == len(result["visual"]) == len(set(captured)) == 30
    assert all(s["cell"][0] <= s["actual_at"] < s["cell"][1] for s in result["samples"])
    assert result["samples"][0]["gap"]["buffered_interval"] == [.233333, .25]
    assert video_store.meta("browser_fingerprint_pending:123") == {}


@pytest.mark.parametrize("observed", [
    {"at": None}, {"at": 2.1}, {"at": .25, "sample_target": .25},
    {"at": .25, "sample_target": .25, "gap": {"previous_end": 2, "next_start": 3,
        "buffered_interval": [0, .5], "requested_at": 1, "target": .25}},
])
def test_sample_time_evidence_cannot_fake_a_midpoint_or_leave_its_cell(observed):
    with pytest.raises(AccessError):
        browser._sample_evidence(observed, 1, 0, 2)


def _native_loading_case(intervals, mode, steps):
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for page JavaScript")
    setup = "let intervals=" + json.dumps(intervals) + ";const mode=" + json.dumps(mode) + ";" + r"""
let now=0, drawn=[], seeks=[];const performance={now:()=>now};
const requestedTime=34.375;
const video={readyState:1,seeking:true,paused:true,error:null,dataset:{},_at:requestedTime,plays:0,
  buffered:{get length(){return intervals.length;},start:i=>intervals[i][0],end:i=>intervals[i][1]},
  scrollIntoView(){if(!this.muted)throw Error('unmuted scroll');},pause(){this.paused=true;},
  play(){if(!this.muted)throw Error('unmuted play');this.plays++;this.paused=false;return Promise.resolve();},
  get currentTime(){return this._at;},set currentTime(value){this._at=value;seeks.push(value);
    const available=intervals.some(r=>r[0]<=value && value<r[1]);
    const decoded=available && !['stuck','gap_stuck'].includes(mode) && value!==requestedTime;
    this.readyState=decoded?2:1;this.seeking=!decoded;}};
const document={visibilityState:'visible',createElement:()=>({getContext:()=>({drawImage:v=>{
  if(v.readyState<2 || v.seeking)throw Error('undecoded frame');drawn.push(v.currentTime);
}}),toDataURL:()=>{if(mode==='cors')throw Error('SecurityError');return 'fixture';}})};
"""
    script = browser._sample_frame_script("const v=video;", 34.375, 16 * 62.5 / 30, 17 * 62.5 / 30)
    run = "const run=()=>JSON.parse(" + script + ");"
    return json.loads(subprocess.run([node, "-e", setup + run + steps +
        "console.log(JSON.stringify({states,drawn,seeks,plays:video.plays}));"],
        capture_output=True, text=True, check=True, timeout=10).stdout)


def test_gap_recovery_uses_later_buffered_ranges_beyond_compact_diagnostics():
    intervals = [[0, .016667], [.233333, .25], [3.001667, 8.988333],
                 [33.136667, 33.153333], [34.7, 37]]
    result = _native_loading_case(intervals, "gap", """
const states=[run()];now=2000;states.push(run());now=2001;states.push(run());
""")
    status, frame = result["states"][1:]
    assert status["buffered"] == intervals[:4]
    assert status["buffered_count"] == 5 and status["buffered_truncated"] is True
    assert status["buffered_complete"] is True
    assert intervals[4] in status["buffered_near_sample"]
    assert frame["gap"]["next_start"] == 34.7
    assert result["drawn"] == [pytest.approx(34.72)]
    assert frame["png"] == "fixture"
    evidence = browser._sample_evidence(frame, 34.375, 16 * 62.5 / 30, 17 * 62.5 / 30)
    assert evidence["gap"]["buffered_interval"] == intervals[4]


def test_buffered_target_after_first_four_intervals_keeps_the_exact_sample():
    intervals = [[0, .016667], [.233333, .25], [3.001667, 8.988333],
                 [33.136667, 33.153333], [34, 35]]
    result = _native_loading_case(intervals, "gap", """
const states=[run()];now=2000;states.push(run());
video.readyState=2;video.seeking=false;now=2001;states.push(run());
""")
    assert result["seeks"] == [] and result["drawn"] == [34.375]
    assert result["states"][1]["buffered_count"] == 5
    assert intervals[4] in result["states"][1]["buffered_near_sample"]
    assert result["states"][-1]["gap"] is None
    assert result["states"][-1]["at"] == result["states"][-1]["sample_target"] == 34.375


@pytest.mark.parametrize("invalid", ["too_many", "overlap", "read_error"])
def test_incomplete_native_range_snapshot_never_captures_or_recovers(invalid):
    intervals = [[i * 2, i * 2 + 1] for i in range(129)] if invalid == "too_many" else [[0, 40], [39, 45]]
    setup = "video.readyState=2;video.seeking=false;"
    if invalid == "read_error":
        setup += "video.buffered.start=()=>{throw Error('changed TimeRanges');};"
    result = _native_loading_case(intervals, "gap", setup + """
const states=[run()];now=9000;states.push(run());
""")
    assert all(state["buffered_complete"] is False for state in result["states"])
    assert all(not state.get("png") and state["preroll"] is None for state in result["states"])
    assert result["drawn"] == result["seeks"] == []
    assert result["plays"] == 0


@pytest.mark.parametrize("outcome", ["decoded", "undecoded", "cors"])
def test_observed_preroll_loads_then_reseeks_without_counting_preroll_frames(outcome):
    intervals = [[0, .016667], [.233333, .25], [3.001667, 8.988333], [33.136667, 33.153333]]
    steps = """
const states=[run()];now=3000;states.push(run());now=3100;states.push(run());
// Normal playback has decoded nearby footage and buffered the required target.
now=3600;video._at=33.4;intervals[3]=[33.136667,36];states.push(run());
now=3700;states.push(run());
"""
    if outcome != "undecoded":
        steps += "video.readyState=2;video.seeking=false;video._at=requestedTime;"
    result = _native_loading_case(intervals, outcome, steps + "now=4200;states.push(run());")
    preroll = result["states"][1]["preroll"]
    assert preroll["buffered_interval"] == intervals[3]
    assert 31.375 <= preroll["target"] < 16 * 62.5 / 30  # loading may start before the cell
    assert result["seeks"] == [preroll["target"], 34.375]
    assert result["states"][3]["preroll"]["phase"] == "reseeking"
    assert result["states"][3]["ready_state"] == 1 and result["states"][3]["seeking"] is True
    assert not any(state.get("png") for state in result["states"][:-1])
    if outcome == "decoded":
        frame = result["states"][-1]
        assert result["drawn"] == [34.375]
        assert browser._sample_evidence(frame, 34.375, 16 * 62.5 / 30, 17 * 62.5 / 30) == {
            "requested_at": 34.375, "actual_at": 34.375,
            "cell": [16 * 62.5 / 30, 17 * 62.5 / 30], "gap": None}
    elif outcome == "cors":
        assert result["states"][-1] == {"error": "frame access denied"}
    else:
        assert not result["states"][-1].get("png") and result["drawn"] == []


@pytest.mark.parametrize("mode", ["stuck", "gap_stuck"])
def test_one_six_play_allowance_covers_seek_gap_and_single_preroll(mode):
    intervals = [[0, .016667], [.233333, .25], [3.001667, 8.988333], [33.136667, 33.153333]]
    if mode == "gap_stuck":
        intervals.append([34.7, 37])
    result = _native_loading_case(intervals, mode, """
const states=[];
for(now=0;now<=25000;now+=1000){video.paused=true;states.push(run());}
""")
    assert result["plays"] == 6
    assert max(state["sample_play_attempts"] for state in result["states"]) == 6
    assert result["drawn"] == [] and not any(state.get("png") for state in result["states"])
    assert len(result["seeks"]) == 1
    if mode == "stuck":
        assert result["states"][-1]["preroll"]["phase"] == "exhausted"
        assert result["states"][-1]["preroll"]["started"] == 3000
        assert result["states"][11]["preroll"]["phase"] == "exhausted"
    else:
        assert all(state["preroll"] is None for state in result["states"])
        assert result["states"][-1]["gap"]["target"] == pytest.approx(34.72)


def test_preroll_requires_an_observed_buffered_point_within_three_seconds():
    result = _native_loading_case([[0, 8], [30, 31.374]], "stuck", """
const states=[];
for(now=0;now<=25000;now+=1000){video.paused=true;states.push(run());}
""")
    assert result["plays"] == 6 and result["seeks"] == result["drawn"] == []
    assert all(state["preroll"] is None and not state.get("png") for state in result["states"])


def test_preroll_wait_keeps_revision_two_partial_samples_and_transaction_bound(
        video_store, browser_cfg, monkeypatch):
    from contextlib import nullcontext
    from src.video.security import Deferred
    monkeypatch.setattr(browser, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda *a: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    elapsed = [0]
    monkeypatch.setattr(browser.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(browser.time, "sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds))
    saved = {"revision": 2, "duration": 62.5, "count": 30, "visual": [["fixture"]] * 16,
             "frame_hashes": ["fixture"] * 16, "variation": [10] * 16,
             "samples": [{"requested_at": (i + .5) * 62.5 / 30, "actual_at": (i + .5) * 62.5 / 30,
                          "cell": [i * 62.5 / 30, (i + 1) * 62.5 / 30], "gap": None} for i in range(16)]}
    video_store.set_meta("browser_fingerprint_pending:123", saved)
    def page(js, *args):
        if "png:c.toDataURL" in js:
            return {"ready_state": 1, "seeking": True, "requested_at": 34.375,
                    "preroll": {"phase": "exhausted", "target": 33.145}}
        return {"duration": 62.5, "ready_state": 2}
    monkeypatch.setattr(browser, "_json", page)
    with pytest.raises(Deferred, match="fingerprint is pending"):
        browser.SafariVideoClient(video_store, browser_cfg).fingerprint({"post_url": "https://x.com/example/status/123"})
    assert 25 <= elapsed[0] < 25.1
    assert video_store.meta("browser_fingerprint_pending:123") == saved
    status = video_store.meta("browser_video_access:123")
    assert status["sample_index"] == status["samples_saved"] == 16
    assert status["preroll"]["phase"] == "exhausted"
    assert not video_store.meta("browser_fingerprint:123")


@pytest.fixture
def browser_cfg(video_cfg):
    return replace(video_cfg, publishing_transport="safari")


@pytest.fixture
def browser_setup(video_store, browser_cfg, ready, at, monkeypatch):
    clock(monkeypatch, at())
    monkeypatch.setattr("src.video.publisher.time.time", lambda: at().timestamp())
    monkeypatch.setattr(browser, "require_browser_owner", lambda: None)
    monkeypatch.setattr("src.guards.content_guard.validate", lambda *a, **k: (True, ""))
    monkeypatch.setattr("src.guards.respect_list.scrub_text_or_skip", lambda t: (t, ""))
    doc = ready()
    row = publisher.reserve(video_store, at(), browser_cfg)
    assert row["transport"] == "safari"
    return row, doc


def fake_composer(monkeypatch, store, doc, *, failure="", receipt="123"):
    calls = []
    class Fake:
        def __init__(self, path, caption, cfg, *, check):
            self.check = check
        def prepare(self):
            assert safari._safari_lock._lock.owned()
            self.check()
            calls.append("upload")
            if failure == "upload":
                raise AccessError("upload failed")
            import time
            return {"ready": True, "sha256": doc["output_sha256"], "checked_at": time.time(), "nonce": "fixture"}
        def submit(self, store, ident, token):
            calls.append("submit")
            assert store.rows("SELECT state FROM reservations WHERE id=?", (ident,))[0]["state"] == "submitting"
            if failure == "before_click":
                raise AccessError("known failure before send permit")
            with store.transaction() as db:
                db.execute("UPDATE reservations SET network_started=1 WHERE id=?", (ident,))
            if failure == "timeout":
                raise TimeoutError("ambiguous click")
            return failure != "refused_click"
        def receipt(self, since):
            return receipt
        def close(self):
            calls.append("close")
    monkeypatch.setattr(browser, "Composer", Fake)
    return calls


def test_video_reuses_browser_lock_and_confirms_receipt(video_store, browser_cfg, browser_setup, monkeypatch):
    row, doc = browser_setup
    calls = fake_composer(monkeypatch, video_store, doc)
    result = browser.SafariVideoClient(video_store, browser_cfg).publish_reserved(row["id"], row["token"])
    assert result is WriteOutcome.SHIPPED
    assert calls == ["upload", "submit", "close"]
    final = video_store.rows("SELECT * FROM reservations")[0]
    assert final["state"] == "confirmed" and final["post_id"] == "123"
    assert video_store.rows("SELECT state FROM slots WHERE reservation=?", (row["id"],))[0]["state"] == "posted"


def test_due_video_cannot_be_starved_by_later_ordinary_replies(video_store, browser_cfg, browser_setup, monkeypatch):
    import threading
    import time
    from src.core.work_priority import BACKGROUND, REPLY, WATCH, scope
    row, doc = browser_setup
    fake_composer(monkeypatch, video_store, doc)
    order, errors, outcomes = [], [], []
    original = browser.Composer.prepare
    def prepare(page):
        order.append("video")
        return original(page)
    monkeypatch.setattr(browser.Composer, "prepare", prepare)
    def reader(label, priority):
        with scope(priority), safari._safari_lock:
            order.append(label)
    def video():
        outcomes.append(browser.SafariVideoClient(video_store, browser_cfg).publish_reserved(row["id"], row["token"]))
    def safe(call):
        try:
            call()
        except BaseException as exc:
            errors.append(exc)
    threads = []
    calls = [lambda: reader("routine", BACKGROUND), lambda: reader("earlier-reply", REPLY), video,
             lambda: reader("later-reply", REPLY), lambda: reader("watched", WATCH)]
    try:
        with safari._safari_lock:
            for call in calls:
                thread = threading.Thread(target=safe, args=(call,))
                threads.append(thread)
                thread.start()
                deadline = time.monotonic() + 3
                while safari._safari_lock._lock.pending() < len(threads) + 1 and not errors and time.monotonic() < deadline:
                    time.sleep(.005)
                assert not errors
                assert safari._safari_lock._lock.pending() == len(threads) + 1
            assert order == []  # queued work cannot preempt the current transaction
    finally:
        for thread in threads:
            thread.join(timeout=5)
    assert not errors and not any(thread.is_alive() for thread in threads)
    assert outcomes == [WriteOutcome.SHIPPED]
    assert order == ["watched", "earlier-reply", "video", "later-reply", "routine"]


@pytest.mark.parametrize("failure", ["upload", "before_click", "refused_click"])
def test_proven_safari_failure_releases_without_faking_a_post(video_store, browser_cfg, browser_setup, monkeypatch, failure):
    row, doc = browser_setup
    fake_composer(monkeypatch, video_store, doc, failure=failure)
    result = browser.SafariVideoClient(video_store, browser_cfg).publish_reserved(row["id"], row["token"])
    assert result is WriteOutcome.FAILED
    assert video_store.rows("SELECT state FROM reservations")[0]["state"] == "failed"
    assert not video_store.rows("SELECT * FROM content_claims")


@pytest.mark.parametrize("failure,receipt", [("timeout", "123"), ("", None)])
def test_ambiguous_safari_send_keeps_permanent_claim(video_store, browser_cfg, browser_setup, monkeypatch, failure, receipt):
    row, doc = browser_setup
    fake_composer(monkeypatch, video_store, doc, failure=failure, receipt=receipt)
    result = browser.SafariVideoClient(video_store, browser_cfg).publish_reserved(row["id"], row["token"])
    assert result is WriteOutcome.UNCONFIRMED
    assert video_store.rows("SELECT state FROM reservations")[0]["state"] == "publish_unknown"
    assert video_store.rows("SELECT * FROM content_claims")


def test_dry_run_does_not_open_or_attach(video_store, browser_cfg, browser_setup, monkeypatch, settings_override):
    row, doc = browser_setup
    settings_override(DRY_RUN=True)
    monkeypatch.setattr(browser, "Composer", lambda *a, **k: pytest.fail("dry-run attached media"))
    assert browser.SafariVideoClient(video_store, browser_cfg).publish_reserved(row["id"], row["token"]) is WriteOutcome.DRY_RUN


def test_direct_video_write_requires_publisher_role(video_store, browser_cfg, browser_setup):
    row, _ = browser_setup
    assert twitter_client.post_video(video_store, browser_cfg, row["id"], row["token"]) is WriteOutcome.REFUSED


def test_browser_submit_consumes_one_reservation_permit(video_store, browser_cfg, browser_setup, monkeypatch, at):
    row, doc = browser_setup
    page = browser.Composer(doc["output_path"], row["caption"], browser_cfg)
    monkeypatch.setattr(page, "ready", lambda **kw: True)
    clicks = []
    monkeypatch.setattr(browser, "_json", lambda js: clicks.append(js) or True)
    evidence = {"ready": True, "sha256": sha256(doc["output_path"]), "checked_at": at().timestamp(), "nonce": page.nonce}
    with video_store.transaction() as db:
        db.execute("UPDATE reservations SET browser_evidence=?", (json.dumps(evidence),))
    publisher.authorize_submit(video_store, row["id"], row["token"], at().timestamp(), browser_cfg)
    with workers.role_lock("publisher"), safari._safari_lock:
        assert page.submit(video_store, row["id"], row["token"])
        with pytest.raises(AccessError, match="consumed"):
            page.submit(video_store, row["id"], row["token"])
    assert len(clicks) == 1


def test_preflight_in_safari_mode_never_requires_api_credentials(video_store, browser_cfg, monkeypatch):
    monkeypatch.setattr("src.video.config.credentials", lambda: pytest.fail("Safari requested API credentials"))
    monkeypatch.setattr(browser.SafariVideoClient, "preflight", lambda *a, **k: {"account_verified": True})
    result = operations.preflight(video_store, browser_cfg, network=True)
    assert not any("OAuth" in b or "API access" in b for b in result["blockers"])
    assert result["status"]["transport"] == "safari"


def test_independent_media_worker_never_reads_safari(video_store, browser_cfg, monkeypatch):
    monkeypatch.setattr(browser.SafariVideoClient, "preflight", lambda *a, **k: pytest.fail("media worker used Safari"))
    assert workers._api_work(video_store, browser_cfg, "media", 100) is None


def test_standalone_safari_publisher_refused(video_store, browser_cfg, monkeypatch):
    monkeypatch.setattr("src.video.config.load", lambda: browser_cfg)
    with pytest.raises(ValueError, match="main.py"):
        workers.run("publisher", once=True)


def test_supervisor_uses_scheduler_for_safari_publishing(video_store, browser_cfg, monkeypatch):
    monkeypatch.setattr("src.video.config.load", lambda: browser_cfg)
    starts = []
    class Child:
        def __init__(self, argv, **kwargs): starts.append(argv[-1])
        def poll(self): return 0
        def wait(self, **kw): return 0
    monkeypatch.setattr(workers.subprocess, "Popen", Child)
    supervisor = workers.Supervisor()
    try:
        supervisor.tick()
        assert starts == ["discovery", "media"]
        assert workers.owns_role("publisher")
    finally:
        supervisor.stop()
    assert not workers.owns_role("publisher")


def test_other_live_bot_process_cannot_be_driven(monkeypatch, tmp_path):
    monkeypatch.setattr(browser.settings, "PROJECT_ROOT", tmp_path)
    (tmp_path / "bot.lock").write_text(str(os.getpid() + 100))
    monkeypatch.setattr(browser.state_store, "bot_holds_lock", lambda *a: True)
    with pytest.raises(AccessError, match="running bot owns Safari"):
        browser.require_browser_owner()


def test_v1_migration_keeps_unknown_api_claim(tmp_path):
    path = tmp_path / "legacy-video.db"
    legacy = SCHEMA.replace(",\n transport TEXT NOT NULL DEFAULT 'api', browser_evidence TEXT NOT NULL DEFAULT '{}'", "")
    with sqlite3.connect(path) as db:
        db.executescript(legacy)
        db.execute("INSERT INTO reservations(id,candidate,state,created,updated,deadline,token,lease,caption,media_id) "
                   "VALUES('held','clip','publish_unknown',1,1,10,'token',10,'caption','777')")
        db.execute("INSERT INTO content_claims VALUES('clip','held')")
        db.execute("PRAGMA user_version=1")
    upgraded = Store(path)
    row = upgraded.rows("SELECT * FROM reservations")[0]
    assert row["state"] == "publish_unknown" and row["media_id"] == "777" and row["transport"] == "api"
    assert upgraded.rows("SELECT * FROM content_claims")
    assert upgraded.rows("PRAGMA user_version")[0]["user_version"] == 2


@pytest.mark.parametrize("field,value", [("nonce", "other"), ("media_ready", False), ("post_enabled", False),
                                        ("progress", True), ("files", []), ("caption", "injected caption")])
def test_changed_composer_never_qualifies(browser_cfg, browser_setup, monkeypatch, field, value):
    row, doc = browser_setup
    page = browser.Composer(doc["output_path"], row["caption"], browser_cfg)
    state = {"nonce": page.nonce, "composer": True, "caption": " ".join(row["caption"].split()),
             "files": [{"name": page.path.name, "size": page.size}], "media_ready": True, "post_enabled": True, "progress": False}
    monkeypatch.setattr(page, "_view", lambda **kw: state)
    assert page.ready()
    state[field] = value
    assert not page.ready()


def test_browser_history_fingerprinting_runs_in_media_worker(video_store, browser_cfg, monkeypatch):
    from src.video import reconcile
    import time
    now = time.time()
    source = {"media_key": "browser:123", "type": "video", "variants": [{"content_type": "video/mp4", "url": "https://video.twimg.com/fixture.mp4"}]}
    original = reconcile.media_fingerprint
    with pytest.raises(AccessError, match="independent media worker"):
        original(source, video_store, browser_cfg, now)
    assert video_store.rows("SELECT * FROM jobs WHERE kind='x_media'")
    calls = []
    def fingerprint(*args, **kwargs):
        calls.append(kwargs)
        return {"fixture": "fingerprint"}
    monkeypatch.setattr(reconcile, "media_fingerprint", fingerprint)
    assert workers._x_media_work(video_store, browser_cfg, "media", now)
    assert calls == [{"offload": False}]
    assert original(source, video_store, browser_cfg, now) == {"fixture": "fingerprint"}


@pytest.mark.parametrize("discarded", [True, False])
def test_upload_probe_can_never_submit(video_store, browser_cfg, browser_setup, monkeypatch, discarded):
    _, doc = browser_setup
    monkeypatch.setattr(browser.SafariVideoClient, "preflight", lambda *a, **kw: None)
    class Probe:
        def __init__(self, *args): pass
        def prepare(self): return {"ready": True}
        def submit(self, *args): pytest.fail("probe tried to click Post")
        def close(self): return discarded
    monkeypatch.setattr(browser, "Composer", Probe)
    if not discarded:
        with pytest.raises(AccessError, match="discard was not confirmed"):
            browser.probe_upload(video_store, browser_cfg, doc["output_path"])
        return
    result = browser.probe_upload(video_store, browser_cfg, doc["output_path"])
    assert result["ready"] and result["draft_discarded"] and result["published"] is False
