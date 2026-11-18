from contextlib import contextmanager
from contextlib import nullcontext
from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from src.video import media, native_source, ranking, reconcile, workers
from src.video.security import AccessError, Deferred, sha256
from src.x import safari, safari_video


POST = "https://x.com/example/status/123"
RESOURCE = "https://video.twimg.com/ext_tw_video/456/pu/pl/video.m3u8"


@pytest.fixture
def observed():
    return {"post_id": "123", "post_url": POST, "media_id": "456",
            "media": [RESOURCE], "user_agent": "fixture Safari"}


@pytest.fixture
def native_payload(observed, at):
    return {"media_key": "browser:123", "post_url": POST, "duration": 4,
            "native_source": native_source.x_media_plan(observed, POST, at().timestamp())}


def test_observation_releases_browser_without_queueing_or_decoding(
        video_store, video_cfg, observed, at, monkeypatch):
    held, visits = [], []
    @contextmanager
    def session():
        held.append(True)
        try:
            yield
        finally:
            held.pop()
    monkeypatch.setattr(safari_video, "browser_session", session)
    monkeypatch.setattr(safari_video.time, "time", lambda: at().timestamp())
    monkeypatch.setattr(safari, "open_url", lambda url: visits.append(url) or True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: visits.append("closed"))
    monkeypatch.setattr(safari_video, "_json", lambda *a: {"duration": 4, "native_media": observed})
    monkeypatch.setattr(native_source, "download", lambda *a: pytest.fail("browser observation downloaded media"))
    client = safari_video.SafariVideoClient(video_store, replace(video_cfg, publishing_transport="safari"))
    result = client.observe_native_media({"post_url": POST})
    assert visits == [POST, "closed"] and held == []
    assert result["native_source"] == native_source.x_media_plan(observed, POST, at().timestamp())
    assert not video_store.rows("SELECT * FROM jobs")
    assert not video_store.rows("SELECT * FROM reservations")
    assert video_store.rows("SELECT amount FROM costs WHERE provider='x_browser'") == [{"amount": 1}]


@pytest.mark.parametrize("change", [
    {"post_id": "124"}, {"post_url": "https://x.com/another/status/124"}, {"media_id": "999"},
    {"media": ["https://video.twimg.com/ext_tw_video/999/pu/video.mp4"]},
    {"media": ["https://elsewhere.example/ext_tw_video/456/pu/video.mp4"]},
    {"media": ["https://video.twimg.com/private/456/video.mp4"]},
    {"media": None}, {"user_agent": "invalid\r\nHeader"},
])
def test_only_exact_post_and_player_bound_public_resources_are_admitted(observed, at, change):
    assert native_source.x_media_plan(observed | change, POST, at().timestamp()) is None


def test_page_resource_binding_ignores_other_players_and_unobserved_urls():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for page JavaScript")
    setup = """
const navigator={userAgent:'fixture Safari'};
const performance={getEntriesByType:()=>[
 {name:'https://video.twimg.com/ext_tw_video/999/pu/other.mp4'},
 {name:'https://video.twimg.com/ext_tw_video/456/pu/pl/video.m3u8'},
 {name:'https://other.example/ext_tw_video/456/pu/video.mp4'},
 {name:'https://video.twimg.com/private/456/video.mp4'}]};
const video={poster:'https://pbs.twimg.com/ext_tw_video_thumb/456/pu/img/frame.jpg',
 currentSrc:'blob:https://x.com/native',querySelectorAll:()=>[]};
"""
    result = json.loads(subprocess.run([node, "-e", setup + native_source.X_PLAYER_MEDIA +
        "console.log(JSON.stringify(playerMedia(video)));"], capture_output=True, text=True, check=True, timeout=10).stdout)
    assert result == {"media_id": "456", "media": [RESOURCE], "user_agent": "fixture Safari",
                      "observed_paths": ["/ext_tw_video/456/pu/pl/video.m3u8"]}


@pytest.mark.parametrize("later_video", [True, False])
def test_audio_only_metadata_waits_for_video_within_one_bounded_browser_transaction(
        video_store, video_cfg, at, monkeypatch, later_video):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for page JavaScript")
    audio = "https://video.twimg.com/ext_tw_video/456/pu/pl/mp4a/64000/audio.m3u8"
    video = "https://video.twimg.com/ext_tw_video/456/pu/pl/avc1/640x360/video.m3u8"
    setup = r"""
let now=0;const resources=AUDIO;
const navigator={userAgent:'fixture Safari'};
const performance={now:()=>now,getEntriesByType:()=>resources.map(name=>({name}))};
const video={poster:'https://pbs.twimg.com/ext_tw_video_thumb/456/pu/img/a.jpg',
  currentSrc:'blob:https://x.com/player',querySelectorAll:()=>[],
  error:null,readyState:0,duration:59,currentTime:0,dataset:{},muted:false,paused:true,plays:0,
  scrollIntoView(){},play(){if(!this.muted)throw Error('unmuted playback');
    this.plays++;this.paused=false;return Promise.resolve();}};
const link={getAttribute:()=>'/example/status/123'};
const article={querySelectorAll:()=>[stamp],querySelector:()=>video};
const stamp={closest:s=>s==='article'?article:s==='a'?link:null};
const location={origin:'https://x.com',hostname:'x.com',pathname:'/example/status/123'};
const document={visibilityState:'visible',querySelectorAll:s=>s.startsWith('article[data-testid')?[article]:[],
  querySelector:()=>null};
""".replace("AUDIO", json.dumps([audio]))
    program = setup + "const run=()=>JSON.parse(" + safari_video._video_metadata_script("123") + ");const states=[];"
    program += "for(let i=0;i<100;i++){now=i*250;"
    if later_video:
        program += "if(i===4)resources.push(" + json.dumps(video) + ");"
    program += "states.push(run());}console.log(JSON.stringify({states,plays:video.plays,muted:video.muted}));"
    result = json.loads(subprocess.run([node, "-e", program], check=True, capture_output=True, text=True, timeout=10).stdout)
    assert result["plays"] == 1 and result["muted"] is True
    assert result["states"][0]["native_media"]["media"] == [audio]

    elapsed, visits, timeouts = [0.0], [], []
    monkeypatch.setattr(safari_video, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari_video.time, "time", lambda: at().timestamp() + elapsed[0])
    monkeypatch.setattr(safari_video.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(safari_video.time, "sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds))
    monkeypatch.setattr(safari, "open_url", lambda url: visits.append(url) or True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: visits.append("closed"))
    monkeypatch.setattr(native_source, "download", lambda *a, **k: pytest.fail("metadata observation decoded audio-only media"))
    saved = {"revision": 2, "visual": [["existing"]] * 8, "samples": [{"actual_at": i} for i in range(8)]}
    video_store.set_meta("browser_fingerprint_pending:123", saved)
    def page(script, timeout):
        assert script == safari_video._video_metadata_script("123"), "metadata did not remain in bounded loading"
        assert 0 < timeout <= min(8, 25 - elapsed[0])
        timeouts.append(timeout)
        return result["states"][int(elapsed[0] * 4)]
    monkeypatch.setattr(safari_video, "_json", page)
    client = safari_video.SafariVideoClient(video_store, replace(video_cfg, publishing_transport="safari"))
    with pytest.raises(Deferred, match="independent media worker" if later_video else "decoded frames remain pending"):
        client.fingerprint({"post_url": POST})
    assert visits == [POST, "closed"]
    assert video_store.meta("browser_fingerprint_pending:123") == saved
    assert not video_store.meta("browser_fingerprint:123")
    assert not video_store.rows("SELECT * FROM reservations")
    if later_video:
        assert elapsed[0] == 1 and len(timeouts) == 5
        job = video_store.rows("SELECT * FROM jobs WHERE kind='x_media'")[0]
        plan = video_store.meta("x_media:" + job["item"])["native_source"]["source_download"]
        assert plan["media"] == [video] and plan["audio_media"] == audio
        assert job["state"] == "pending" and job["attempts"] == 0
    else:
        assert elapsed[0] == 25 and len(timeouts) == 100 and timeouts[-1] == .25
        assert not video_store.rows("SELECT * FROM jobs")
        assert video_store.meta("browser_video_access:123")["native_media"]["observed_paths"] == [
            "/ext_tw_video/456/pu/pl/mp4a/64000/audio.m3u8"]


def test_unknown_player_resource_paths_are_bounded_diagnostics_never_download_admission(at):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for page JavaScript")
    resources = ["https://video.twimg.com/ext_tw_video/999/pu/unknown.m4s?secret=elsewhere",
                 "https://other.example/ext_tw_video/456/pu/unknown.m4s?secret=elsewhere"]
    resources += [f"https://video.twimg.com/ext_tw_video/456/pu/old-format/{i}.m4s?secret=fixture" for i in range(20)]
    setup = ("const navigator={userAgent:'fixture Safari'};const resources=" + json.dumps(resources) + ";"
        "const performance={getEntriesByType:()=>resources.map(name=>({name}))};"
        "const v={poster:'https://pbs.twimg.com/ext_tw_video_thumb/456/img/a.jpg',currentSrc:'blob:x',querySelectorAll:()=>[]};")
    result = json.loads(subprocess.run([node, "-e", setup + native_source.X_PLAYER_MEDIA +
        "console.log(JSON.stringify(playerMedia(v)));"], capture_output=True, text=True, check=True, timeout=10).stdout)
    assert result["media"] == []
    assert result["observed_paths"] == [f"/ext_tw_video/456/pu/old-format/{i}.m4s" for i in range(12)]
    assert "secret" not in json.dumps(result)
    assert native_source.x_media_plan(result | {"post_id": "123", "post_url": POST}, POST, at().timestamp()) is None


def test_pending_native_decode_avoids_new_browser_reads_and_refreshes_only_observed_expired_plan(
        video_store, video_cfg, observed, at, monkeypatch):
    cfg = replace(video_cfg, publishing_transport="safari")
    now = at().timestamp()
    item = {"post_url": POST, "media_key": "browser:123"}
    with pytest.raises(Deferred):
        reconcile.queue_native_fingerprint(video_store, item, observed, 4, cfg, now)
    job = video_store.rows("SELECT * FROM jobs")[0]
    monkeypatch.setattr(safari_video.time, "time", lambda: now + 30)
    monkeypatch.setattr(safari, "open_url", lambda *a: pytest.fail("pending decode opened Safari again"))
    with pytest.raises(Deferred):
        safari_video.SafariVideoClient(video_store, cfg).fingerprint(item)
    assert not video_store.rows("SELECT * FROM costs")
    assert reconcile.native_fingerprint_result(video_store, "123", now + 3601) is None
    with pytest.raises(Deferred):
        reconcile.queue_native_fingerprint(video_store, item, observed, 4, cfg, now + 3601)
    assert video_store.rows("SELECT * FROM jobs") == [job]
    plan = video_store.meta("x_media:" + job["item"])["native_source"]["source_download"]
    assert plan["captured_at"] == now + 3601
    with video_store.transaction() as db:
        db.execute("UPDATE jobs SET state='dead',attempts=4,error='retry limit'")
    assert reconcile.queue_native_fingerprint(video_store, item, observed, 4, cfg, now + 3700) is None
    assert video_store.rows("SELECT state,attempts FROM jobs") == [{"state": "dead", "attempts": 4}]


@pytest.mark.parametrize("failure", [None, "partial", "wrong_hash", "wrong_duration"])
def test_native_decode_requires_whole_actual_file_and_retains_hash_bound_page_evidence(
        video_store, video_cfg, native_payload, at, tmp_path, monkeypatch, failure):
    monkeypatch.setattr(reconcile, "ASSETS", tmp_path / "decode")
    deadlines = []
    def download(doc, path, *args, **kwargs):
        deadlines.append(media._job_deadline)
        path.write_bytes(b"actual owned fixture bytes")
    monkeypatch.setattr(native_source, "download", download)
    monkeypatch.setattr(reconcile, "probe", lambda *a: {"duration": 5 if failure == "wrong_duration" else 4})
    def fingerprint(path, info, cfg):
        return {"sha256": "wrong" if failure == "wrong_hash" else sha256(path),
                "duration": info["duration"], "visual": [["0" * 16] * 3] * (3 if failure == "partial" else 4), "audio": [1]}
    monkeypatch.setattr(reconcile, "fingerprint", fingerprint)
    if failure:
        with pytest.raises(AccessError):
            reconcile.media_fingerprint(native_payload, video_store, video_cfg, at().timestamp(), offload=False)
    else:
        result = reconcile.media_fingerprint(native_payload, video_store, video_cfg, at().timestamp(), offload=False)
        assert result["source_evidence"]["sha256"] == result["sha256"]
        assert result["source_evidence"]["decoded_samples"] == len(result["visual"]) == 4
        assert result["source_evidence"]["post_url"] == POST
        assert result["source_evidence"]["media_urls"] == [RESOURCE]
    assert deadlines[0] is not None and media._job_deadline is None
    assert not video_store.rows("SELECT * FROM reservations")


def test_expired_or_altered_native_plan_cannot_download(video_store, video_cfg, native_payload, at, monkeypatch):
    monkeypatch.setattr(native_source, "download", lambda *a: pytest.fail("invalid plan reached network"))
    with pytest.raises(Deferred, match="fresh normal-page"):
        reconcile.media_fingerprint(native_payload, video_store, video_cfg, at().timestamp() + 3601, offload=False)
    native_payload["native_source"]["source_download"]["media"] = ["https://video.twimg.com/ext_tw_video/999/other.mp4"]
    with pytest.raises(AccessError, match="identity"):
        reconcile.media_fingerprint(native_payload, video_store, video_cfg, at().timestamp(), offload=False)


@pytest.mark.parametrize("failure", ["watermark", "score"])
def test_known_ineligible_preparation_spends_no_novelty_reads_and_resumes_after_real_repair(
        video_store, video_cfg, ready, at, monkeypatch, failure):
    cfg = replace(video_cfg, allow_unknown_momentum=True)
    now = at().timestamp()
    doc = ready()
    doc["novelty"] = {"state": "unchecked"}
    if failure == "watermark":
        doc["qc"]["watermark_present"] = False
    else:
        doc["ranking"] = {"total": 47, "components": {"fit": 16, "entertainment": 13,
            "quality": 8, "freshness": 10, "novelty": None, "momentum": None}}
    original = json.loads(json.dumps(doc))
    fp = {"sha256": doc["original_sha256"], "visual": [["0" * 16] * 3] * 4}
    video_store.save_candidate("clip1", doc, now, state="held", fingerprint=fp)
    class Search:
        calls = 0
        def search(self, *args):
            self.calls += 1
            return {"data": [], "includes": {"media": []}, "meta": {}}
    client = Search()
    with pytest.raises(Deferred, match="eligible preparation"):
        reconcile.novelty(video_store, video_store.candidate("clip1"), client, cfg, now)
    assert client.calls == 0 and video_store.candidate("clip1")["document"] == original
    doc["qc"]["watermark_present"] = True
    doc["ranking"] = {"total": 95}
    video_store.save_candidate("clip1", doc, now, state="held", fingerprint=fp)
    assert reconcile.novelty(video_store, video_store.candidate("clip1"), client, cfg, now) == "checked_no_match"
    assert client.calls > 0


def test_observed_audio_file_is_excluded_and_master_beyond_early_resources_wins(observed, at):
    prefix = "https://video.twimg.com/amplify_video/456/"
    audio_file = prefix + "aud/mp4a/0/0/128000/w3kjgINMyI7xe0uK.mp4"
    audio = prefix + "pl/mp4a/128000/oaU2zQ6kyLO-rUzx.m3u8"
    video = prefix + "pl/avc1/720x1198/4smBdZVLweGW997Q.m3u8"
    master = prefix + "pl/master.m3u8"
    doc = native_source.x_media_plan(observed | {"media": [audio_file, audio, video, master]}, POST, at().timestamp())
    assert doc["source_download"]["media"] == [master, video]
    assert doc["source_download"]["audio_media"] == audio
    assert audio_file not in doc["source_evidence"]["media_urls"]
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for page JavaScript")
    raw = [audio_file] * 12 + [audio, video, master]
    setup = ("const navigator={userAgent:'fixture Safari'};const resources=" + json.dumps(raw) + ";"
        "const performance={getEntriesByType:()=>resources.map(name=>({name}))};"
        "const v={poster:'https://pbs.twimg.com/amplify_video_thumb/456/img/a.jpg',currentSrc:'blob:x',querySelectorAll:()=>[]};")
    result = json.loads(subprocess.run([node, "-e", setup + native_source.X_PLAYER_MEDIA +
        "console.log(JSON.stringify(playerMedia(v)));"], capture_output=True, text=True, check=True, timeout=10).stdout)
    assert result["media"] == [master, video, audio]


@pytest.mark.parametrize("case", ["allowed", "over_views", "saved_original"])
def test_x_source_capture_uses_same_bound_split_plan_and_keeps_view_and_original_checks(
        video_cfg, observed, at, tmp_path, monkeypatch, case):
    now = at().timestamp()
    prefix = "https://video.twimg.com/amplify_video/456/"
    sources = [prefix + "aud/mp4a/0/0/128000/audio.mp4", prefix + "pl/mp4a/128000/audio.m3u8",
               prefix + "pl/avc1/720x1198/video.m3u8"]
    evidence = observed | {"media": sources}
    payload = {"canonical_url": POST, "published": now - 100, "creator": "example", "views": "50,001 views" if case == "over_views" else "100 views",
               "native_media": evidence, "media": sources, "user_agent": "fixture Safari"}
    monkeypatch.setattr(safari_video, "browser_session", lambda: nullcontext())
    monkeypatch.setattr(safari, "open_url", lambda *a: True)
    monkeypatch.setattr(safari, "close_front_tab", lambda: None)
    monkeypatch.setattr(safari, "_run_js", lambda *a, **k: json.dumps(payload))
    doc = {"platform": "x", "source_id": "123", "canonical_url": POST, "creator": "example"}
    if case == "saved_original":
        original = tmp_path / "original.mp4"
        original.write_bytes(b"unchanged inspected source")
        doc.update(original_path=str(original), original_sha256=sha256(original))
    if case == "over_views":
        with pytest.raises(AccessError, match="50000"):
            native_source.capture({"document": doc}, video_cfg, now)
        assert "source_download" not in doc
    else:
        native_source.capture({"document": doc}, video_cfg, now)
        if case == "saved_original":
            assert original.read_bytes() == b"unchanged inspected source" and "source_download" not in doc
        else:
            assert doc["source_download"]["media"] == [sources[2]]
            assert doc["source_download"]["audio_media"] == sources[1]
            assert sources[0] not in doc["source_evidence"]["media_urls"]
        assert doc["source_metrics"]["views"] == 100


def test_unusable_complete_asset_tries_next_observed_alternative_and_keeps_costs(
        video_store, video_cfg, observed, at, tmp_path, monkeypatch):
    one = "https://video.twimg.com/ext_tw_video/456/pu/vid/640x360/first.mp4"
    two = "https://video.twimg.com/ext_tw_video/456/pu/vid/640x360/second.mp4"
    doc = native_source.x_media_plan(observed | {"media": [one, two]}, POST, at().timestamp())
    calls = []
    def request(url, *, sink, **kwargs):
        calls.append(url)
        sink.write(b"audio-only" if url == one else b"whole-video")
    def validate(path):
        if path.read_bytes() == b"audio-only":
            raise AccessError("no video stream")
    monkeypatch.setattr(native_source, "request", request)
    destination = tmp_path / "complete.mp4"
    native_source.download(doc, destination, video_cfg, video_store, at().timestamp(), validate=validate)
    assert calls == [one, two] and destination.read_bytes() == b"whole-video"
    assert sum(r["amount"] for r in video_store.rows("SELECT amount FROM costs WHERE kind='download_bytes'")) == 21


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="actual decode needs FFmpeg")
def test_observed_split_playlists_produce_full_real_video_audio_fingerprint(
        video_store, video_cfg, observed, at, tmp_path, monkeypatch):
    media.ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=96x96:rate=10", "-t", "4", "-an", "-c:v", "libx264",
        "-g", "10", "-f", "hls", "-hls_time", "1", "-hls_list_size", "0",
        "-hls_segment_filename", str(tmp_path / "video%d.ts"), str(tmp_path / "video.m3u8")], video_cfg)
    media.ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "4", "-vn", "-c:a", "aac",
        "-f", "hls", "-hls_time", "1", "-hls_list_size", "0",
        "-hls_segment_filename", str(tmp_path / "audio%d.ts"), str(tmp_path / "audio.m3u8")], video_cfg)
    prefix = "https://video.twimg.com/amplify_video/456/"
    audio_file = prefix + "aud/mp4a/0/0/128000/w3kjgINMyI7xe0uK.mp4"
    audio = prefix + "pl/mp4a/128000/audio.m3u8"
    video = prefix + "pl/avc1/720x1198/video.m3u8"
    doc = native_source.x_media_plan(observed | {"media": [audio_file, audio, video]}, POST, at().timestamp())
    requests = []
    def request(url, *, sink, **kwargs):
        requests.append(url)
        assert url != audio_file
        sink.write((tmp_path / url.rsplit("/", 1)[-1]).read_bytes())
    monkeypatch.setattr(native_source, "request", request)
    monkeypatch.setattr(reconcile, "ASSETS", tmp_path / "managed")
    result = reconcile.media_fingerprint({"post_url": POST, "native_source": doc, "duration": 4},
                                       video_store, video_cfg, at().timestamp(), offload=False)
    assert len(result["visual"]) == result["source_evidence"]["decoded_samples"] >= 4
    assert result["audio"] and len(result["sha256"]) == 64
    assert result["source_evidence"]["sha256"] == result["sha256"]
    assert audio in requests and video in requests and audio_file not in requests
    assert media._job_deadline is None
