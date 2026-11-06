"""Native-video attachments using the same Safari primitives as Replies.

The main scheduler owns browser work. Standalone checks/workers refuse while
another process owns it; media/discovery processes never drive Safari.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlencode
import uuid

from ..core import account, config as core_config, settings, state_store, work_priority
from ..core.logger import log
from ..guards.active_hours import require_active
from ..video import config
from ..video.security import AccessError, Deferred, sha256
from . import safari, x_urls


def require_browser_owner():
    if state_store.bot_holds_lock(str(settings.PROJECT_ROOT)):
        try:
            pid = int((Path(settings.PROJECT_ROOT) / "bot.lock").read_text().strip())
        except (OSError, ValueError):
            raise AccessError("cannot verify the live Safari owner") from None
        if pid != os.getpid():
            raise AccessError("the running bot owns Safari; its video scheduler must do this work")


@contextmanager
def publisher_session():
    from ..video.workers import owns_role, role_lock
    require_browser_owner()
    if owns_role("publisher"):
        yield
    else:
        with role_lock("publisher"):
            yield


@contextmanager
def browser_session():
    require_active()
    with publisher_session():
        # Preparation/novelty reads need to survive a normal browser transaction
        # to retain their FIFO position among ready Replies. Retrying every five
        # seconds discarded that place indefinitely under continuous activity.
        # Routine archive work still yields promptly to the due publisher.
        lock = safari._safari_lock._lock
        wait = 60 if work_priority.current_priority() <= work_priority.REPLY else 5
        if not lock.acquire(timeout=wait):
            raise Deferred("Safari busy; video read deferred without occupying the publisher", retry_after=10)
        try:
            require_active()
            yield
        finally:
            lock.release()


def _json(js, timeout=8):
    raw = safari._run_js(js, timeout, log_prefix="[VIDEO-SAFARI]")
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        raise AccessError("Safari did not return readable page evidence") from None


def _require_transaction():
    from ..video.workers import owns_role
    require_browser_owner()
    if not owns_role("publisher") or not safari._safari_lock._lock.owned():
        raise AccessError("video composer requires the publisher role and shared Safari lock")


_PAGE = r"""(() => {
  const host = ['x.com','www.x.com','twitter.com','www.twitter.com'].includes(location.hostname);
  const profile = document.querySelector('[data-testid="AppTabBar_Profile_Link"]');
  const norm = t => (t || '').replace(/\s+/g, ' ').trim();
  const dialogs = [...new Set([...document.querySelectorAll('[data-testid^="tweetTextarea_"][contenteditable="true"]')]
    .filter(e=>e.getClientRects().length && e.closest('[role="dialog"]')).map(e=>e.closest('[role="dialog"]')))];
  const d = dialogs.length === 1 ? dialogs[0] : null;
  const v = d?.querySelector('video');
  const b = d?.querySelector('[data-testid="tweetButton"]');
  const uploading = [...(d?.querySelectorAll('[role="progressbar"]') || [])].some(p => {
    if(p.closest('[data-testid="dual-phase-countdown-circle"]')) return false;
    const value=p.getAttribute('aria-valuenow');
    return value===null ? !!p.getClientRects().length : Number(value)>0 && Number(value)<Number(p.getAttribute('aria-valuemax') || 100);
  });
  return JSON.stringify({host, account:profile?.getAttribute('href') || '',
    composer:!!d, nonce:d?.dataset.botVideo || '',
    caption:norm(d?.querySelector('[data-testid^="tweetTextarea_"][contenteditable="true"]')?.innerText),
    files:d?._botVideoFiles || [...(d?.querySelector('input[type="file"]')?.files || [])].map(f=>({name:f.name,size:f.size,type:f.type})),
    video:!!v, duration:Number.isFinite(v?.duration) ? v.duration : null,
    media_ready:!!v && v.readyState >= 2 && !v.error,
    post_enabled:!!b && !b.disabled && b.getAttribute('aria-disabled') !== 'true',
    progress:uploading,
    error:norm(d?.querySelector('[role="alert"]')?.textContent)});
})()"""

_POSTS = r"""(() => {
  if (!['x.com','www.x.com','twitter.com','www.twitter.com'].includes(location.hostname)) return '{}';
  function count(el) {
    if (!el) return null;
    const m=(el.getAttribute('aria-label') || el.textContent || '').match(/(?:^|\s)(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)(?:\s|$|\.)/);
    return m ? Math.round(Number(m[1].replace(/,/g,''))*({k:1000,m:1000000}[m[2].toLowerCase()] || 1)) : null;
  }
  const posts = [...document.querySelectorAll('article[data-testid="tweet"]')].flatMap(a => {
    const own = el => el?.closest('article[data-testid="tweet"]') === a
      && !el.closest('[data-testid="quoteTweet"], div[role="link"]');
    const t = [...a.querySelectorAll('time[datetime]')].find(t => own(t) && t.closest('a[href*="/status/"]'));
    const link = t?.closest('a[href*="/status/"]');
    const m = (link?.getAttribute('href') || '').match(/^\/([A-Za-z0-9_]{1,15})\/status\/(\d+)$/);
    const user = [...a.querySelectorAll('[data-testid="User-Name"] a[href]')].find(own);
    if (!m || user?.getAttribute('href')?.toLowerCase() !== '/' + m[1].toLowerCase()) return [];
    const inArticle = el => el?.closest('article[data-testid="tweet"]') === a;
    const v = a.querySelector('video'), player = a.querySelector('[data-testid="videoPlayer"]');
    const metric = selector => {const el=a.querySelector(selector); return count(own(el) ? el : null);};
    return [{id:m[2], author:m[1], text:[...a.querySelectorAll('[data-testid="tweetText"]')].find(own)?.innerText || '',
      created_at:t.dateTime, url:'https://x.com/'+m[1]+'/status/'+m[2],
      video:!!((v && inArticle(v)) || (player && inArticle(player))), source:inArticle(v) ? v.currentSrc : '',
      duration:inArticle(v) && Number.isFinite(v.duration) ? v.duration : null,
      urls:[...a.querySelectorAll('[data-testid="tweetText"] a[href]')].map(e=>e.getAttribute('title') || e.href),
      likes:metric('[data-testid="like"], [data-testid="unlike"]'),
      shares:metric('[data-testid="retweet"], [data-testid="unretweet"]'),
      replies:metric('[data-testid="reply"]'), views:metric('a[href$="/analytics"]')}];
  });
  const text = document.querySelector('main')?.innerText || '';
  return JSON.stringify({posts, receipts:[...document.querySelectorAll('[data-testid="toast"] a[href*="/status/"]')].map(a=>a.href),
    height:document.documentElement.scrollHeight, y:window.scrollY,
    bottom:window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 8,
    loading:!!document.querySelector('[role="progressbar"]'),
    empty:!document.querySelector('article[data-testid="tweet"]') && /No results for|No posts yet|hasn.t posted/i.test(text),
    error:/Something went wrong|Rate limit exceeded|Try again later/i.test(text)});
})()"""


# X can pause its native player again while an unbuffered seek is loading. A
# one-shot play marker then strands that seek forever. Retry only normal muted
# playback, at most six times per pending sample and once a second overall. This
# never changes origin restrictions or treats metadata as a decoded frame.
_FRAME_LOADING = r"""
const rangeState = value => {
  const count=value?.length ?? 0, intervals=[];
  if(!Number.isInteger(count) || count<0)return {count,intervals,complete:false};
  let complete=count<=128;
  try {
    for(let i=0;i<Math.min(count,128);i++){
      const start=value.start(i),end=value.end(i);
      if(!Number.isFinite(start) || !Number.isFinite(end) || start<0 || start>=end
        || (i && start<intervals[i-1][1])){complete=false;break;}
      intervals.push([start,end]);
    }
  } catch(e) {complete=false;}
  return {count,intervals,complete};
};
const loading = (phase,sample=null) => {
  if(!v || v.error || !v.paused)return;
  const state=v._botFrameLoading || (v._botFrameLoading={attempts:0,last:0,positioned:false});
  if(state.phase!==phase){state.phase=phase;state.phaseAttempts=0;}
  const now=performance.now();
  if(state.phaseAttempts>=6 || (sample && sample.playAttempts>=6) || (state.attempts && now-state.last<1000))return;
  v.preload='auto';v.muted=true;
  if(!state.positioned){
    v.scrollIntoView({block:'center',inline:'nearest',behavior:'auto'});
    state.positioned=true;
  }
  state.attempts++;state.phaseAttempts++;state.last=now;
  if(sample)sample.playAttempts++;
  try { v.play().catch(e=>{v.dataset.botPlaybackError=e.name;}); }
  catch(e){v.dataset.botPlaybackError=e.name;}
};
const playerState = () => {
  const buffered=rangeState(v?.buffered),seekable=rangeState(v?.seekable),target=v?._botFrameSample?.target;
  const distance=r=>target<r[0]?r[0]-target:target>=r[1]?target-r[1]:0;
  return {ready_state:v?.readyState,seeking:v?.seeking,
    current_time:v?.currentTime,paused:v?.paused,network_state:v?.networkState,
    media_error:v?.error?.code || null,playback_error:v?.dataset.botPlaybackError || null,
    play_attempts:v?._botFrameLoading?.attempts || 0,sample_play_attempts:v?._botFrameSample?.playAttempts || 0,
    buffered:buffered.intervals.slice(0,4),buffered_count:buffered.count,buffered_complete:buffered.complete,
    buffered_truncated:buffered.count>4,
    buffered_near_sample:Number.isFinite(target)?[...buffered.intervals].sort((a,b)=>distance(a)-distance(b)).slice(0,4):[],
    seekable:seekable.intervals.slice(0,4),seekable_count:seekable.count,seekable_complete:seekable.complete,
    visibility:document.visibilityState};
};
"""


_FRAME_SAMPLE = r"""
if(!v)return JSON.stringify(playerState());
let sample=v._botFrameSample;
if(!sample || sample.requested!==requested){
  sample=v._botFrameSample={requested,target:requested,started:performance.now(),gap:null,playAttempts:0,preroll:null};
}
const status=()=>JSON.stringify({...playerState(),requested_at:requested,
  sample_target:sample.target,cell:[cellStart,cellEnd],gap:sample.gap,preroll:sample.preroll});
const observedRanges=rangeState(v.buffered);
// Diagnostics are compact; recovery needs the complete bounded native ranges.
// An incomplete snapshot cannot establish either a gap or a pre-roll anchor.
if(!observedRanges.complete)return status();
const buffered=observedRanges.intervals;
if(sample.preroll && sample.preroll.phase!=='reseeking'){
  const preroll=sample.preroll;
  if(preroll.phase==='exhausted')return status();
  if(v.error || performance.now()-preroll.started>=8000){
    v.pause();preroll.phase='exhausted';return status();
  }
  loading('preroll:'+requested,sample);
  if(!v.paused && !v.seeking && v.readyState>=2){
    if(preroll.playing_at===undefined)preroll.playing_at=performance.now();
    preroll.phase='playing';
    if(performance.now()>preroll.playing_at
      && (buffered.some(r=>r[0]<=sample.target && sample.target<r[1]) || v.currentTime>=sample.target)){
      // Warm the native decoder only. Re-seek and validate the real sample on
      // a later poll; no pre-roll frame, including one outside the cell, counts.
      v.pause();v.dataset.botSeekLoad='';v.currentTime=sample.target;
      preroll.phase='reseeking';
    }
  }
  return status();
}
// A seek into a demonstrated buffered hole cannot be decoded at its midpoint.
// After ordinary loading has had a turn, allow an actual frame elsewhere in
// this same temporal cell. Every cell still needs its own decoded canvas sample.
if(!sample.gap && v.seeking && v.readyState<2 && !v.error && performance.now()-sample.started>=2000){
  const before=buffered.filter(r=>r[1]<requested), after=buffered.filter(r=>r[0]>requested);
  if(!buffered.some(r=>r[0]<=requested && requested<r[1]) && before.length && after.length){
    const choices=buffered.flatMap(range=>{
      const lo=Math.max(range[0],cellStart),hi=Math.min(range[1],cellEnd);
      if(!(lo<hi))return [];
      const inset=Math.min(.02,(hi-lo)/2);
      const target=Math.max(lo+inset,Math.min(hi-inset,requested));
      return [{target,buffered_interval:range}];
    }).sort((a,b)=>Math.abs(a.target-requested)-Math.abs(b.target-requested));
    if(choices.length){
      const choice=choices[0];
      sample.target=choice.target;
      sample.gap={requested_at:requested,target:choice.target,
        previous_end:Math.max(...before.map(r=>r[1])),next_start:Math.min(...after.map(r=>r[0])),
        buffered_interval:choice.buffered_interval};
      v.pause();v.muted=true;v.dataset.botSeekLoad='';v.currentTime=sample.target;
      return status();
    }
  }
}
// Some native seeks expose a buffered keyframe just before the desired cell
// but never finish loading its midpoint. Try that observed point once, using
// the same six-play allowance, then re-seek the unchanged requested sample.
if(!sample.gap && !sample.preroll && (v.seeking || v.readyState<2) && !v.error
  && sample.playAttempts<6 && performance.now()-sample.started>=3000){
  const choices=buffered.flatMap(range=>{
    const lo=Math.max(0,requested-3,range[0]),hi=Math.min(requested-.08,range[1]);
    if(!(lo<hi))return [];
    const inset=Math.min(.02,(hi-lo)/2);
    return [{target:Math.max(lo+inset,Math.min(hi-inset,requested-1)),buffered_interval:range}];
  }).sort((a,b)=>Math.abs(a.target-requested)-Math.abs(b.target-requested));
  if(choices.length){
    sample.preroll={...choices[0],started:performance.now(),phase:'seeking'};
    v.pause();v.muted=true;v.dataset.botSeekLoad='';v.currentTime=sample.preroll.target;
    return status();
  }
}
if((v.seeking || v.readyState<2) && !v.error){v.dataset.botSeekLoad='loading';loading('seek:'+sample.target,sample);}
if(v.seeking || v.readyState<2)return status();
if(v.dataset.botSeekLoad==='loading'){
  v.pause();v.dataset.botSeekLoad='ready';
  if(Math.abs(v.currentTime-sample.target)>.08){v.currentTime=sample.target;return status();}
}
const insideCell=v.currentTime>=cellStart && v.currentTime<cellEnd;
const insideRange=!sample.gap || (v.currentTime>=sample.gap.buffered_interval[0] && v.currentTime<sample.gap.buffered_interval[1]);
if(Math.abs(v.currentTime-sample.target)>.08 || !insideCell || !insideRange){
  v.pause();v.currentTime=sample.target;return status();
}
v.pause();
try{const c=document.createElement('canvas');c.width=64;c.height=64;c.getContext('2d').drawImage(v,0,0,64,64);
  return JSON.stringify({at:v.currentTime,requested_at:requested,sample_target:sample.target,
    cell:[cellStart,cellEnd],gap:sample.gap,png:c.toDataURL('image/png')});}
catch(e){return JSON.stringify({error:'frame access denied'});}
"""


def _sample_frame_script(select, at, cell_start, cell_end):
    return ("(()=>{" + select + _FRAME_LOADING +
            f"const requested={at},cellStart={cell_start},cellEnd={cell_end};" + _FRAME_SAMPLE + "})()")


def _sample_evidence(observed, requested, cell_start, cell_end):
    """Keep real sample times; buffered metadata alone can never supply a frame."""
    import math
    actual, target = observed.get("at"), observed.get("sample_target", requested)
    if (any(type(value) not in (int, float) or not math.isfinite(value) for value in (actual, target))
            or not cell_start <= actual < cell_end or not cell_start <= target < cell_end
            or abs(actual - target) > .08):
        raise AccessError("rendered video sample time is unverified")
    gap = observed.get("gap")
    if gap:
        if not isinstance(gap, dict):
            raise AccessError("rendered video gap evidence is unverified")
        before, after = gap.get("previous_end"), gap.get("next_start")
        interval = gap.get("buffered_interval")
        if (not isinstance(interval, list) or len(interval) != 2
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in (before, after, *interval))
                or not before < requested < after or not interval[0] <= target < interval[1]
                or not interval[0] <= actual < interval[1] or interval[0] <= requested < interval[1]
                or gap.get("requested_at") != requested or gap.get("target") != target):
            raise AccessError("rendered video gap evidence is unverified")
    elif target != requested:
        raise AccessError("rendered video sample moved without buffered gap evidence")
    return {"requested_at": requested, "actual_at": actual, "cell": [cell_start, cell_end], "gap": gap}


def _normal(text):
    return " ".join(str(text).split())


def _choose_file(path, timeout=10):
    """Use the native Open sheet. Never press Return in an unverified composer."""
    escaped = safari._escape_for_applescript(str(path))
    script = '''
    tell application "Safari" to activate
    tell application "System Events" to tell process "Safari"
        set frontmost to true
        repeat 30 times
            if exists sheet 1 of window 1 then exit repeat
            delay 0.1
        end repeat
        if not (exists sheet 1 of window 1) then error "No native file picker"
        keystroke "g" using {command down, shift down}
        delay 0.4
        set the clipboard to "''' + escaped + '''"
        keystroke "v" using command down
        delay 0.2
        if not (exists sheet 1 of window 1) then error "File picker lost"
        key code 36
        delay 0.7
        if not (exists sheet 1 of window 1) then error "Open sheet lost"
        if exists button "Upload" of sheet 1 of window 1 then
            click button "Upload" of sheet 1 of window 1
        else if exists button "Open" of sheet 1 of window 1 then
            click button "Open" of sheet 1 of window 1
        else if exists button "Ouvrir" of sheet 1 of window 1 then
            click button "Ouvrir" of sheet 1 of window 1
        else
            error "Expected file-picker Upload/Open button missing"
        end if
    end tell
    '''
    if not safari._run_applescript(script, timeout_s=timeout):
        raise AccessError("Safari file selection failed before submission")


class Composer:
    def __init__(self, path, caption, cfg, *, check=lambda: None):
        self.path = Path(path).resolve(strict=True)
        self.caption, self.cfg, self.check = caption, cfg, check
        self.nonce = uuid.uuid4().hex
        self.opened = False
        self.picker_started = False
        self.prepare_deadline = None
        self.last_readiness = None
        self.size = self.path.stat().st_size
        if self.path.suffix.lower() != ".mp4" or not 0 < self.size <= cfg.max_download_bytes:
            raise AccessError("video must be a bounded local MP4")
        self.digest = sha256(self.path)

    def _remaining(self):
        remaining = 8 if self.prepare_deadline is None else self.prepare_deadline - time.monotonic()
        if remaining <= 0:
            raise AccessError("Safari attachment preparation deadline reached")
        return min(8, remaining)

    def _view(self, *, check=True):
        require_active()
        if check:
            self.check()
        result = _json(_PAGE, self._remaining())
        if not result.get("host") or result.get("account", "").casefold() != "/" + account.current().handle.casefold():
            raise AccessError("Safari is not signed in to the expected account")
        return result

    def ready(self, *, check=True):
        state = self._view(check=check)
        files = state.get("files", [])
        if state.get("error"):
            raise AccessError("X composer reported an attachment error")
        readiness = (state.get("media_ready") is True, state.get("post_enabled") is True,
                     state.get("progress") is True, len(files) == 1)
        if readiness != getattr(self, "last_readiness", None):
            log.info("[VIDEO] Attachment readiness: decoded=%s post_enabled=%s processing=%s one_file=%s", *readiness)
            self.last_readiness = readiness
        return bool(state.get("nonce") == self.nonce and state.get("composer")
            and state.get("caption") == _normal(self.caption) and len(files) == 1
            and files[0].get("name") == self.path.name and files[0].get("size") == self.size
            and state.get("media_ready") and state.get("post_enabled") and not state.get("progress"))

    def prepare(self):
        require_active()
        self.check()
        if core_config.dry_run() or not config.live():
            raise AccessError("dry-run/disabled video never uploads through Safari")
        _require_transaction()
        began = time.monotonic()
        self.prepare_deadline = began + self.cfg.browser_upload_seconds
        self.opened = safari.open_url("https://x.com/intent/post?" + urlencode({"text": self.caption}))
        if not self.opened:
            raise AccessError("Safari composer could not be opened")
        for _ in range(16):
            state = _json(_PAGE, self._remaining())
            if not state.get("account"):
                time.sleep(.5)
                continue
            state = self._view()
            if state.get("composer") and state.get("caption") == _normal(self.caption):
                break
            time.sleep(.5)
        else:
            raise AccessError("expected new-post composer/caption was not visible")
        if state.get("files") or state.get("video"):
            raise AccessError("existing attachment/draft must not be overwritten")
        nonce = json.dumps(self.nonce)
        clicked = _json('''(() => {const ds=[...new Set([...document.querySelectorAll('[data-testid^="tweetTextarea_"][contenteditable="true"]')].filter(e=>e.getClientRects().length && e.closest('[role="dialog"]')).map(e=>e.closest('[role="dialog"]')))];
          if(ds.length!==1) return 'false'; const d=ds[0], input=d.querySelector('input[data-testid="fileInput"]');
          if(!input || input.files.length) return 'false'; d.dataset.botVideo=''' + nonce + ''';
          input.addEventListener('change',()=>{d._botVideoFiles=[...input.files].map(f=>({name:f.name,size:f.size,type:f.type}));},{once:true,capture:true});
          input.click(); return 'true';})()''', self._remaining())
        if not clicked:
            raise AccessError("video attachment control missing")
        self.picker_started = True
        _choose_file(self.path, self._remaining())
        self.picker_started = False
        while time.monotonic() - began < self.cfg.browser_upload_seconds:
            if self.ready():
                return {"ready": True, "sha256": self.digest, "filename": self.path.name,
                        "bytes": self.size, "checked_at": time.time(), "nonce": self.nonce,
                        "account": account.current().handle, "transport": "safari"}
            time.sleep(.5)
        raise AccessError("Safari upload did not become ready within the bounded transaction")

    def submit(self, store, ident, token):
        """One durable send permit; even direct callers cannot submit twice."""
        require_active()
        _require_transaction()
        if not config.live() or not self.ready(check=False):
            raise AccessError("video submission is disabled or attachment changed")
        now = time.time()
        with store.transaction() as db:
            flags = {r[0]: json.loads(r[1]) for r in db.execute("SELECT key,value FROM meta WHERE key IN ('paused','shutdown')")}
            row = db.execute("SELECT * FROM reservations WHERE id=? AND token=? AND transport='safari' "
                "AND state='submitting' AND network_started IS NULL AND deadline>=? AND lease>=?", (ident, token, now + 20, now)).fetchone()
            if not row or flags.get("paused", True) or flags.get("shutdown", False):
                raise AccessError("Safari send permit is absent, paused or consumed")
            proof = json.loads(row["browser_evidence"])
            if proof.get("nonce") != self.nonce or proof.get("sha256") != self.digest or row["caption"] != self.caption:
                raise AccessError("Safari composer does not match its reservation")
            db.execute("UPDATE reservations SET network_started=? WHERE id=?", (now, ident))
        # No keyboard submit: click only our verified new-post composer.
        return _json('''(() => {const state=JSON.parse(''' + _PAGE + ''');
          const d=document.querySelector('[data-bot-video="''' + self.nonce + '''"]');
          const b=d?.querySelector('[data-testid="tweetButton"]');
          const files=state.files || [];
          if(!state.host || !d || !b || !state.media_ready || !state.post_enabled || state.progress
             || state.account.toLowerCase()!==''' + json.dumps("/" + account.current().handle.casefold()) + '''
             || state.nonce!==''' + json.dumps(self.nonce) + '''
             || files.length!==1 || files[0].name!==''' + json.dumps(self.path.name) + ''' || files[0].size!==''' + str(self.size) + '''
             || state.caption!==''' + json.dumps(_normal(self.caption)) + ''') return 'false';
          b.click(); return 'true';})()''')

    def receipt(self, since):
        visited = set()
        for attempt in range(15):
            require_active()
            snapshot = _json(_POSTS)
            rows = snapshot.get("posts", [])
            matches = []
            for post in rows:
                stamp = x_urls.posted_at(post.get("url", ""))
                if (post.get("author", "").casefold() == account.current().handle.casefold()
                        and _normal(post.get("text", "")) == _normal(self.caption) and post.get("video")
                        and stamp and since - 5 <= stamp.timestamp() <= time.time() + 5):
                    matches.append(post["id"])
            if len(set(matches)) == 1:
                return matches[0]
            if len(set(matches)) > 1:
                return None
            for raw in snapshot.get("receipts", []):
                url = x_urls.canonical_status_url(raw)
                stamp = x_urls.posted_at(url)
                if (url and url not in visited and x_urls.author(url) == account.current().handle.casefold()
                        and stamp and since - 5 <= stamp.timestamp() <= time.time() + 5):
                    visited.add(url)
                    safari._run_js("location.href=" + json.dumps(url) + "; 'receipt';", 5)
                    break
            if attempt == 3 and not visited:
                # The composer route can remain blank after success and the
                # transient toast may contain no status link. Read our profile
                # in this same tab; exact author/text/video/time checks still
                # decide confirmation, never the navigation itself.
                profile = "https://x.com/" + account.current().handle
                safari._run_js("if(['x.com','www.x.com','twitter.com','www.twitter.com'].includes(location.hostname))"
                               "{location.href=" + json.dumps(profile) + ";} 'profile-receipt';", 5)
            time.sleep(1)
        return None

    def close(self):
        if not self.opened:
            return True
        discarded = False
        try:
            if self.picker_started:
                safari._run_applescript('''tell application "System Events" to tell process "Safari"
                  if exists sheet 1 of window 1 then
                    if exists button "Cancel" of sheet 1 of window 1 then
                      click button "Cancel" of sheet 1 of window 1
                    else if exists button "Annuler" of sheet 1 of window 1 then
                      click button "Annuler" of sheet 1 of window 1
                    end if
                  end if
                end tell''', timeout_s=5)
            # Only discard the composer this object created; never another draft.
            raw = safari._run_js('''(() => {const d=document.querySelector('[data-bot-video="''' + self.nonce + '''"]');
              if(!d) return 'absent'; const b=d.querySelector('[data-testid="app-bar-close"]');
              if(!b) return 'missing-close'; b.click(); return 'closed';})()''', 5)
            discarded = raw == "absent"
            if raw == "closed":
                for _ in range(15):
                    # X labels Save as Confirm and Discard as Cancel. Select by
                    # visible action, never the affirmative button by position.
                    safari._run_js('''(() => {const buttons=[...document.querySelectorAll('[data-testid="confirmationSheetConfirm"],[data-testid="confirmationSheetCancel"]')]
                      .filter(b=>/^(Discard|Supprimer)$/i.test(b.innerText.trim()) && /Save post|Save draft|Enregistrer/i.test(b.closest('[role="dialog"],[role="alertdialog"]')?.innerText || ''));
                      if(buttons.length===1) buttons[0].click();})()''', 5)
                    state = safari._run_js("document.querySelector('[data-bot-video=\"" + self.nonce + "\"]') ? 'present' : 'absent'", 5)
                    if state == "absent":
                        discarded = True
                        break
                    time.sleep(.2)
        finally:
            safari.close_front_tab()
        return discarded


class SafariVideoClient:
    transport = "safari"
    scope = "visible Safari pages; no match does not establish global absence"

    def __init__(self, store, cfg):
        self.store, self.cfg = store, cfg

    def preflight(self, *, publishing=False, force=False):
        proof = self.store.meta("safari_account_proof", {})
        if (not force and proof.get("account", "").casefold() == account.current().handle.casefold()
                and 0 <= time.time() - proof.get("checked_at", 0) < 60):
            return {"account_verified": True, "transport": "safari", "api_required": False}
        with browser_session():
            if not safari.open_url("https://x.com/home"):
                raise AccessError("Safari could not open X")
            try:
                state = {}
                for _ in range(16):
                    state = _json(_PAGE)
                    if state.get("account"):
                        break
                    time.sleep(.5)
                if not state.get("host") or state.get("account", "").casefold() != "/" + account.current().handle.casefold():
                    raise AccessError("Safari login/account could not be verified")
            finally:
                safari.close_front_tab()
        self.store.set_meta("safari_account_proof", {"account": account.current().handle, "checked_at": time.time()})
        return {"account_verified": True, "transport": "safari", "api_required": False}

    def publish_reserved(self, ident, token):
        from .twitter_client import post_video
        if core_config.dry_run():
            return post_video(self.store, self.cfg, ident, token)
        with publisher_session():
            return post_video(self.store, self.cfg, ident, token)

    def _scan(self, url, cursor=None):
        cursor = cursor or {"offset": 0, "last": []}
        if not isinstance(cursor, dict) or type(cursor.get("offset")) is not int or cursor["offset"] < 0:
            raise AccessError("invalid browser history cursor")
        if cursor["offset"] > 60:
            raise Deferred("bounded visible history window reached; older archive remains incomplete", retry_after=86400)
        limit = self.cfg.request_budget - (0 if getattr(self, "critical_reads", False) else self.cfg.publishing_request_reserve)
        with browser_session():
            if not self.store.budget("x_browser", "reads", 1, limit, time.time()):
                raise AccessError("browser read budget exhausted")
            if not safari.open_url(url):
                raise AccessError("Safari page failed to open")
            try:
                time.sleep(2)
                posts = {}
                def collect():
                    snapshot = _json(_POSTS)
                    if snapshot.get("error"):
                        raise AccessError("X page unavailable or rate limited")
                    posts.update((post["id"], post) for post in snapshot.get("posts", []))
                    return snapshot
                for _ in range(cursor["offset"]):
                    collect()  # replay can reflow; no observed viewport may be skipped
                    safari._run_js("window.scrollBy(0, window.innerHeight * 1.5); 'scrolled'", 5)
                    time.sleep(.15)
                before = collect()
                safari._run_js("window.scrollBy(0, window.innerHeight * 1.5); 'scrolled'", 5)
                time.sleep(1)
                after = collect()
                # A fresh search can render its explicit empty state after the
                # shell stops showing a spinner. Blank DOM is never no-match.
                for _ in range(8):
                    if posts or after.get("empty"):
                        break
                    time.sleep(.5)
                    after = collect()
                if not posts and not after.get("empty"):
                    raise AccessError("unreadable X page is not an empty search")
                end = bool(after.get("empty") and not after.get("loading"))
                if (posts and sorted(posts) == sorted(cursor.get("last", [])) and after.get("bottom")
                        and not after.get("loading") and before.get("height") == after.get("height")):
                    # Confirm the bottom again; a blank/intermediate viewport is never enough.
                    time.sleep(2)
                    previous = set(posts)
                    final = collect()
                    end = (final.get("bottom") and not final.get("loading") and set(posts) == previous
                           and final.get("height") == after.get("height"))
            finally:
                safari.close_front_tab()
        data, media = [], []
        for post in posts.values():
            item = {"id": post["id"], "text": post["text"], "created_at": post["created_at"],
                    "entities": {"urls": [{"expanded_url": u} for u in post["urls"]]}}
            if post["video"]:
                key = "browser:" + post["id"]
                item["attachments"] = {"media_keys": [key]}
                source = post.get("source", "")
                variants = [{"url": source, "content_type": "video/mp4"}] if re.match(r"^https://video\.twimg\.com/.*\.mp4(?:\?|$)", source) else []
                media.append({"media_key": key, "type": "video", "variants": variants, "post_url": post["url"]})
            data.append(item)
        meta = {"scope": self.scope}
        if not end:
            meta["next_token"] = {"offset": cursor["offset"] + 1, "last": sorted(posts)}
        return {"data": data, "includes": {"media": media}, "meta": meta}

    def timeline(self, cursor=None):
        return self._scan("https://x.com/" + account.current().handle, cursor)

    def fingerprint(self, item):
        """Read rendered frames when X exposes only a blob URL. Never bypass CORS."""
        import base64
        import hashlib
        import io
        import math
        from PIL import Image, ImageStat
        from ..video.media import visual_hash
        url = item.get("post_url", "")
        match = re.fullmatch(r"https://x\.com/[A-Za-z0-9_]{1,15}/status/(\d+)", url)
        if not match:
            raise AccessError("exact video post URL is required for visible-frame matching")
        post_id = match[1]
        cached = self.store.meta("browser_fingerprint:" + post_id)
        if cached:
            return cached
        limit = self.cfg.request_budget - (0 if getattr(self, "critical_reads", False) else self.cfg.publishing_request_reserve)
        if not self.store.budget("x_browser", "reads", 1, limit, time.time()):
            raise AccessError("browser fingerprint read budget exhausted")
        with browser_session():
            if not safari.open_url(url):
                raise AccessError("video post could not be opened")
            deadline = time.monotonic() + 25
            try:
                select = ("const a=[...document.querySelectorAll('article[data-testid=\"tweet\"]')].find(a=>"
                    "[...a.querySelectorAll('a[href*=\"/status/\"] time')].some(t=>t.closest('article')===a"
                    " && !t.closest('[data-testid=\"quoteTweet\"], div[role=\"link\"]')"
                    " && t.closest('a')?.getAttribute('href')?.split('?')[0]?.endsWith('/status/" + post_id + "')));"
                    "const v=a?.querySelector('video');")
                info = {}
                while time.monotonic() < deadline:
                    info = _json("(()=>{" + select + _FRAME_LOADING +
                        "if(v && v.readyState<2)loading('metadata');"
                        "const expected=['x.com','www.x.com'].includes(location.hostname) && location.pathname.endsWith('/status/" + post_id + "');"
                        "return JSON.stringify({duration:Number.isFinite(v?.duration)?v.duration:null,"
                        "article:!!a,video:!!v,...playerState(),error:v?.error?.code || null,"
                        "expected_page:expected,host:location.hostname,"
                        "visible_status_links:expected?[...document.querySelectorAll('article time')].map(t=>t.closest('a')?.getAttribute('href')).slice(0,8):[],"
                        "message:expected?(document.querySelector('main')?.innerText || '').slice(0,400):''});})()")
                    if info.get("duration") and (info.get("ready_state") or 0) >= 2:
                        break
                    time.sleep(.25)
                duration = info.get("duration")
                if not duration or not .5 <= duration <= 86400:
                    self.store.set_meta("browser_video_access:" + post_id, {"checked_at": time.time(), "phase": "metadata", **info})
                    raise AccessError("native video duration unavailable")
                self.store.set_meta("browser_video_access:" + post_id, {"checked_at": time.time(), "phase": "frame_loading", **info})
                if (info.get("ready_state") or 0) < 2:
                    raise Deferred("native video metadata loaded but decoded frames remain pending", retry_after=30)
                count = min(30, max(4, math.ceil(duration)))
                progress_key = "browser_fingerprint_pending:" + post_id
                progress = self.store.meta(progress_key, {})
                if progress.get("duration") != duration or progress.get("count") != count or progress.get("revision") != 2:
                    progress = {"revision": 2, "duration": duration, "count": count,
                                "visual": [], "frame_hashes": [], "variation": [], "samples": []}
                sequence, variation = progress["visual"], progress["variation"]
                if len(progress["samples"]) != len(sequence):
                    raise AccessError("saved visible video sample timing is incomplete")
                self.store.set_meta(progress_key, progress)  # record even a first-frame stall
                # Short resumable batches keep an old long video from monopolizing
                # the Reply browser. Partial fingerprints never satisfy dedup.
                from ..video.startup import waiting_reason
                batch = count if waiting_reason(self.store) else 8
                for index in range(len(sequence), min(count, len(sequence) + batch)):
                    at = min(duration - .05, (index + .5) * duration / count)
                    cell_start, cell_end = index * duration / count, (index + 1) * duration / count
                    _json("(()=>{" + select + "if(!v)return '{}';v.pause();v.muted=true;v.dataset.botSeekLoad='';v._botFrameSample=null;v.currentTime=" + str(at) + ";return '{}';})()")
                    frame = None
                    evidence = None
                    observed = {}
                    while time.monotonic() < deadline:
                        observed = _json(_sample_frame_script(select, at, cell_start, cell_end))
                        if observed.get("error"):
                            self.store.set_meta("browser_video_access:" + post_id, {"checked_at": time.time(),
                                "phase": "canvas", "requested_at": at, "sample_index": index, **observed})
                            raise AccessError("X video frames are not readable under browser origin policy")
                        if observed.get("png"):
                            evidence = _sample_evidence(observed, at, cell_start, cell_end)
                            encoded = observed["png"]
                            if not encoded.startswith("data:image/png;base64,") or len(encoded) > 100000:
                                raise AccessError("invalid rendered video frame")
                            with Image.open(io.BytesIO(base64.b64decode(encoded.split(",", 1)[1], validate=True))) as image:
                                if image.size != (64, 64):
                                    raise AccessError("rendered video frame dimensions changed")
                                frame = image.convert("L")
                            break
                        time.sleep(.08)
                    if frame is None:
                        self.store.set_meta("browser_video_access:" + post_id, {"checked_at": time.time(),
                            "phase": "seek", "requested_at": at, "sample_index": index, "samples_saved": len(sequence), **observed})
                        raise Deferred("visible video fingerprint is pending; continue its saved samples", retry_after=30)
                    progress["frame_hashes"].append(hashlib.sha256(frame.tobytes()).hexdigest())
                    variation.append(ImageStat.Stat(frame).stddev[0])
                    sequence.append(visual_hash(frame))
                    progress["samples"].append(evidence)
                    self.store.set_meta(progress_key, progress)
                if len(sequence) < count:
                    raise Deferred("visible video fingerprint is pending; continue its saved samples", retry_after=30)
                if sum(v > 4 for v in variation) < count * .8 or len({tuple(f) for f in sequence}) < 3:
                    raise AccessError("blank/static video frames cannot establish a sequence fingerprint")
                result = {"sha256": hashlib.sha256("".join(progress["frame_hashes"]).encode()).hexdigest(),
                          "visual": sequence, "audio": [], "duration": duration,
                          "samples": progress["samples"],
                          "method": "visible browser canvas sequence; audio unavailable", "post_url": url}
                self.store.set_meta("browser_fingerprint:" + post_id, result)
                self.store.set_meta(progress_key, {})
                return result
            finally:
                safari.close_front_tab()

    def search(self, query, cursor=None):
        query = query.replace("-is:retweet", "-filter:retweets").replace("has:videos", "filter:videos")
        return self._scan("https://x.com/search?" + urlencode({"q": query, "f": "live"}), cursor)

    def metrics(self, post_id):
        if not str(post_id).isdigit():
            raise AccessError("invalid post identifier")
        with browser_session():
            if not safari.open_url("https://x.com/" + account.current().handle + "/status/" + str(post_id)):
                raise AccessError("status page did not open")
            try:
                time.sleep(2)
                rows = [p for p in _json(_POSTS).get("posts", []) if p["id"] == str(post_id)]
            finally:
                safari.close_front_tab()
        if len(rows) != 1:
            raise AccessError("exact status metrics unavailable")
        row = rows[0]
        return {"data": {"public_metrics": {"like_count": row["likes"], "retweet_count": row["shares"], "reply_count": row["replies"]}},
                "includes": {"media": [{"type": "video", "public_metrics": {"view_count": row["views"]}}]}}


def probe_upload(store, cfg, path):
    """Explicit operator diagnostic: upload and discard; no submit call exists here."""
    client = SafariVideoClient(store, cfg)
    client.preflight(force=True)
    with browser_session():
        page = Composer(path, "BANGER upload check 😄\nSynthetic SI diagnostic; unpublished.", cfg)
        try:
            evidence = page.prepare()
        finally:
            discarded = page.close()
        if not discarded:
            raise AccessError("upload was ready but draft discard was not confirmed; inspect Safari drafts")
        return {**evidence, "published": False, "diagnostic_only": True, "draft_discarded": True}
