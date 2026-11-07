"""Normal-page video evidence and bounded downloads, without private endpoints."""
import json
import math
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urljoin, urlsplit

from .security import AccessError, Deferred, request


CDNS = {
    "x": ("video.twimg.com",),
    "instagram": ("cdninstagram.com", "fbcdn.net"),
    "tiktok": ("tiktokcdn.com", "tiktokcdn-us.com", "tiktokcdn-eu.com", "tiktok.com", "byteoversea.com", "ibytedtos.com"),
    "rednote": ("xhscdn.com", "xiaohongshu.com"),
}


X_PLAYER_MEDIA = r"""
const playerMedia = video => {
  const key=(video?.poster||'').match(/\/(?:ext_tw_video_thumb|amplify_video_thumb)\/(\d+)\//)?.[1];
  if(!key)return null;
  const observed=[video.currentSrc,...[...video.querySelectorAll('source[src]')].map(s=>s.src),
    ...performance.getEntriesByType('resource').map(r=>r.name)];
  const kind=path=>/\/pl\/[^/]+\.m3u8$/.test(path)?0:
    /\/vid\/(?:avc1\/)?\d+x\d+\/(?!init[.-]|segment[.-]|chunk[.-]|frag[.-])[^/]+\.mp4$/.test(path)?1:
    /\/pl\/(?:avc1|hvc1|hev1|vp09|av01)\/\d+x\d+\/[^/]+\.m3u8$/.test(path)?2:
    /\/pl\/(?:mp4a|opus)\/(?:\d+\/)?[^/]+\.m3u8$/.test(path)?3:99;
  const bound=[...new Set(observed.filter(raw=>{try{const url=new URL(raw);
    return typeof raw==='string' && raw.length<=4096 && url.protocol==='https:'
      && url.hostname==='video.twimg.com' && !url.username && !url.password
      && (!url.port || url.port==='443') && new RegExp('/(?:ext_tw_video|amplify_video)/'+key+'/').test(url.pathname);
    }catch(e){return false;}}))];
  const media=bound.filter(raw=>kind(new URL(raw).pathname)<99)
    .sort((a,b)=>kind(new URL(a).pathname)-kind(new URL(b).pathname)).slice(0,12);
  return {media_id:key,media,user_agent:navigator.userAgent,
    observed_paths:[...new Set(bound.map(raw=>new URL(raw).pathname))].slice(0,12)};
};
"""


def x_resource_kind(url):
    path = urlsplit(url).path
    patterns = (r"/pl/[^/]+\.m3u8$", r"/vid/(?:avc1/)?\d+x\d+/(?!init[.-]|segment[.-]|chunk[.-]|frag[.-])[^/]+\.mp4$",
                r"/pl/(?:avc1|hvc1|hev1|vp09|av01)/\d+x\d+/[^/]+\.m3u8$",
                r"/pl/(?:mp4a|opus)/(?:\d+/)?[^/]+\.m3u8$")
    return next((index for index, pattern in enumerate(patterns) if re.search(pattern, path)), None)


def x_media_plan(observed, post_url, now):
    """Validate resources already observed for this exact normal-page player."""
    from .connectors import canonical
    if (not isinstance(observed, dict) or not isinstance(observed.get("media"), list)
            or type(now) not in (int, float) or not math.isfinite(now)):
        return None
    try:
        source = canonical("x", post_url)
        actual_source = canonical("x", observed.get("post_url", ""))
    except (TypeError, ValueError):
        return None
    source_id = source.rsplit("/", 1)[-1]
    key = observed.get("media_id")
    ua = observed.get("user_agent")
    if (observed.get("post_id") != source_id or actual_source.casefold() != source.casefold()
            or not isinstance(key, str) or not re.fullmatch(r"[0-9]{1,30}", key)
            or not isinstance(ua, str) or not 0 < len(ua) <= 1000 or any(c in ua for c in "\r\n")):
        return None
    urls = []
    for url in observed["media"][:12]:
        try:
            parsed = urlsplit(url)
            if (media_host("x", url) == "video.twimg.com" and len(url) <= 4096
                    and re.search(r"/(?:ext_tw_video|amplify_video)/" + re.escape(key) + r"/", parsed.path)
                    and x_resource_kind(url) is not None and url not in urls):
                urls.append(url)
        except (AccessError, TypeError, ValueError):
            continue
    urls.sort(key=x_resource_kind)
    videos = [url for url in urls if x_resource_kind(url) != 3]
    audio = next((url for url in urls if x_resource_kind(url) == 3), None)
    if not videos:
        return None
    result = {"platform": "x", "source_id": source_id, "canonical_url": source,
        "source_download": {"version": 1, "platform": "x", "source_id": source_id,
            "media_id": key, "captured_at": now, "expires_at": now + 3600,
            "user_agent": ua, "media": videos[:3]},
        "source_evidence": {"kind": "normal_page_player", "post_url": source, "post_id": source_id,
            "media_id": key, "observed_at": now, "media_urls": urls}}
    if audio:
        result["source_download"]["audio_media"] = audio
    return result


def media_host(platform, url):
    p = urlsplit(url)
    host = p.hostname or ""
    allowed = CDNS.get(platform, ())
    if (p.scheme != "https" or p.username or p.password or p.port not in (None, 443)
            or not any(host == suffix or host.endswith("." + suffix) for suffix in allowed)):
        raise AccessError("normal player supplied an unapproved source CDN")
    return host


def view_upper_bound(value):
    """Do not call rounded 50K proof of <=50000; use its rounding interval."""
    if type(value) is int:
        return value if value >= 0 else None
    if not isinstance(value, str):
        return None
    # Bind the whole leading count, including localized thousands groups.
    # Searching for any numeric suffix can turn '50 001 views' into one view.
    match = re.match(r"^\s*([0-9]+(?:[, \u00a0\u202f][0-9]{3})*(?:\.[0-9]+)?)\s*([KMB])?\s*(?:views?|vues?)\b", value, re.I)
    if not match:
        return None
    number, suffix = match.groups()
    number = re.sub(r"[, \u00a0\u202f]", "", number)
    if not suffix:
        return int(number) if number.isdigit() else None
    factor = {"K": 1000, "M": 1_000_000, "B": 1_000_000_000}[suffix.upper()]
    decimals = len(number.split(".")[1]) if "." in number else 0
    return math.ceil(float(number) * factor + factor / 10 ** decimals / 2) - 1


def script(platform, source_id):
    # These are page-owned data and visible nodes in the already opened normal
    # page. No fetch/XHR, cookie access, hidden API or play/click action occurs.
    return r'''JSON.stringify((()=>{const platform=PLATFORM, id=IDENT;
      PLAYER_MEDIA_HELPER
      const visible=e=>!!(e&&e.getClientRects().length);
      const meta=k=>document.querySelector('meta[property="'+k+'"],meta[name="'+k+'"]')?.content||'';
      const canonical=document.querySelector('link[rel="canonical"]')?.href||location.href;
      const videos=[...document.querySelectorAll('video')].filter(visible);
      let scope=document, video=videos.length===1?videos[0]:null, title=meta('og:title'), published='', creator='', views=null;
      let boundPlayer=false;
      const urls=[];
      if(platform==='x'){
        const articles=[...document.querySelectorAll('article')];
        const primary=a=>[...a.querySelectorAll('a[href*="/status/"]')]
          .find(l=>l.querySelector('time')&&!l.closest('[data-testid="quoteTweet"]'));
        scope=articles.find(a=>{const link=primary(a);return link&&new RegExp('/status/'+id+'(?:[/?]|$)').test(link.href);});
        if(!scope)return {};
        const exact=primary(scope);
        published=exact?.querySelector('time')?.dateTime||'';
        creator=new URL(exact.href).pathname.split('/')[1];
        title=scope.querySelector('[data-testid="tweetText"]')?.innerText||'';
        const ownVideos=[...scope.querySelectorAll('video')].filter(v=>visible(v)
          &&!v.closest('[data-testid="quoteTweet"]')&&!v.closest('div[role="link"]'));
        video=ownVideos.length===1?ownVideos[0]:null;boundPlayer=true;
        const counter=[...scope.querySelectorAll('a[href*="/analytics"]')].find(visible);
        views=counter?.getAttribute('aria-label')||counter?.innerText||null;
        if(views&&!/views?|vues?/i.test(views))views+=' views';
      }else{
        const all=[];
        const visit=(o,depth=0)=>{if(!o||typeof o!=='object'||depth>12||all.length>1000)return;
          if(o['@type']==='VideoObject')all.push(o);
          if(Array.isArray(o))o.slice(0,100).forEach(v=>visit(v,depth+1));
          else Object.values(o).slice(0,100).forEach(v=>visit(v,depth+1));};
        document.querySelectorAll('script[type="application/ld+json"]').forEach(s=>{try{visit(JSON.parse(s.textContent));}catch(e){}});
        const identities=o=>[o.url,o.embedUrl,o['@id']].filter(u=>typeof u==='string'&&u);
        const matches=u=>{try{const link=new URL(u,location.href),page=new URL(canonical);
          return link.hostname.replace(/^www\./,'')===page.hostname.replace(/^www\./,'')
            &&link.pathname.split('/').includes(id);}catch(e){return false;}};
        const own=all.filter(o=>identities(o).some(matches));
        const data=own[0]||(all.length===1&&!identities(all[0]).length?all[0]:null);
        if(!data&&all.some(o=>identities(o).length))return {};
        boundPlayer=!!data;
        if(data){published=data.uploadDate||data.datePublished||'';title=data.name||title;
          creator=typeof data.author==='string'?data.author:data.author?.name||'';
          if(typeof data.contentUrl==='string')urls.push(data.contentUrl);}
        published=published||meta('video:release_date')||meta('article:published_time');
        if(meta('og:video:secure_url'))urls.push(meta('og:video:secure_url'));
        if(meta('og:video'))urls.push(meta('og:video'));
        const raw=document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__')?.textContent;
        if(platform==='tiktok'&&raw){try{const root=JSON.parse(raw);
          const item=root.__DEFAULT_SCOPE__?.['webapp.video-detail']?.itemInfo?.itemStruct;
          if(item&&String(item.id)===id){published=Number(item.createTime);title=item.desc||title;
            creator=item.author?.uniqueId||creator;views=item.stats?.playCount??null;boundPlayer=true;
            const address=item.video?.playAddr;if(typeof address==='string')urls.push(address);}
        }catch(e){}}
      }
      if(video&&boundPlayer){video.muted=true;video.preload='metadata';
        if(video.currentSrc)urls.push(video.currentSrc);
        video.querySelectorAll('source[src]').forEach(s=>urls.push(s.src));
        if(platform==='x'){
          urls.push(...(playerMedia(video)?.media||[]));
        }}
      return {canonical_url:canonical,id,published,creator,title,views,
        native_media:platform==='x'&&video&&boundPlayer?{...playerMedia(video),post_id:id,post_url:canonical}:null,
        media:urls.filter(u=>/^https:\/\//.test(u)).slice(0,12),user_agent:navigator.userAgent};})())'''.replace(
            "PLATFORM", json.dumps(platform)).replace("IDENT", json.dumps(source_id)).replace("PLAYER_MEDIA_HELPER", X_PLAYER_MEDIA)


def capture(row, cfg, now):
    from .connectors import canonical, timestamp
    from ..x import safari
    from ..x.safari_video import browser_session
    doc = row["document"]
    platform, url = doc["platform"], doc["canonical_url"]
    with browser_session():
        if not safari.open_url(url):
            raise AccessError("source page did not open")
        try:
            payload = {}
            for _ in range(8):
                raw = safari._run_js(script(platform, doc["source_id"]), timeout_s=5, target_url=url)
                if raw and len(raw) <= 100000:
                    payload = json.loads(raw)
                if payload.get("published") and payload.get("media"):
                    break
                time.sleep(.5)
        finally:
            safari.close_front_tab()
    if canonical(platform, payload.get("canonical_url", "")) != url:
        raise AccessError("source page canonical identity differs from candidate")
    published = timestamp(payload.get("published") or None)
    if published is None or not 0 < published <= now:
        raise AccessError("source publication timestamp unavailable")
    doc.update(published_at=published, creator=str(payload.get("creator") or doc["creator"])[:128],
               title=str(payload.get("title", ""))[:2000],
               publication_evidence="Publication timestamp from the exact normal source page")
    if platform == "x":
        doc["source_metrics"] = {"views": view_upper_bound(payload.get("views")), "observed_at": now,
                                 "source_url": url, "displayed": str(payload.get("views", ""))[:200]}
        from .ranking import source_gate
        reason = source_gate(doc, now)
        if reason:
            raise AccessError(reason)
    if doc.get("original_sha256") and Path(doc.get("original_path", "")).is_file():
        return doc  # refresh publication/metrics without touching inspected bytes
    if platform == "x":
        native = x_media_plan(payload.get("native_media"), url, now)
        if native:
            doc.update(source_download=native["source_download"], source_evidence=native["source_evidence"],
                       access_status="normal source page media captured")
            return doc
    media = []
    for source in payload.get("media", []):
        try:
            media_host(platform, source)
            if platform == "x" and x_resource_kind(source) not in (0, 1):
                continue  # split tracks need the bound pair above, not an audio-only fallback
            if source not in media:
                media.append(source)
        except (AccessError, ValueError):
            continue
    if not media:
        raise AccessError("normal page exposes no supported source video")
    ua = payload.get("user_agent", "")
    if not isinstance(ua, str) or not ua or len(ua) > 1000 or any(c in ua for c in "\r\n"):
        raise AccessError("invalid normal-page user agent")
    media.sort(key=x_resource_kind if platform == "x" else lambda source: ".m3u8" in urlsplit(source).path)
    doc["source_download"] = {"version": 1, "platform": platform, "source_id": doc["source_id"],
        "captured_at": now, "expires_at": now + 3600, "user_agent": ua, "media": media[:3]}
    doc["access_status"] = "normal source page media captured"
    return doc


def download(doc, destination, cfg, store, now, *, validate=None):
    """Copy observed MP4s or unencrypted VOD HLS through the pinned HTTPS reader."""
    from . import media
    plan = doc["source_download"]
    platform = doc["platform"]
    if (plan.get("platform") != platform or plan.get("source_id") != doc["source_id"]
            or not 0 <= now - plan.get("captured_at", 0) < 3600 or now >= plan.get("expires_at", 0)):
        raise AccessError("source player media reference expired or mismatched")
    headers = {"User-Agent": plan["user_agent"], "Referer": doc["canonical_url"]}
    total = 0
    def fetch(url, sink, *, playlist=False):
        nonlocal total
        host = media_host(platform, url)
        if not store.budget(platform, "requests", 1, cfg.request_budget - cfg.publishing_request_reserve, now):
            raise Deferred("source request budget exhausted")
        ceiling = min(1_000_000 if playlist else cfg.max_download_bytes, cfg.max_download_bytes - total)
        if ceiling <= 0:
            raise AccessError("source exceeds aggregate per-file download cap")
        allowance = int(store.reserve_up_to(platform, "download_bytes", ceiling, cfg.download_budget_bytes, now))
        if allowance <= 0:
            raise Deferred("source download budget exhausted")
        before = sink.tell()
        try:
            timeout = cfg.task_timeout_seconds
            if media._job_deadline is not None:
                timeout = min(timeout, media._job_deadline - time.monotonic())
            if timeout <= 0:
                raise TimeoutError("source download job deadline")
            request(url, hosts={host}, headers=headers, sink=sink, max_bytes=allowance, timeout=timeout,
                mime=({"application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl", "text/plain"}
                      if playlist else {"video/mp4", "video/webm", "video/mp2t", "audio/mp4", "audio/aac", "audio/mpeg", "application/octet-stream"}))
        except AccessError as exc:
            if allowance < ceiling and str(exc) == "response exceeds byte budget":
                raise Deferred("source download budget insufficient") from exc
            raise
        finally:
            used = sink.tell() - before
            total += used
            store.refund_budget(platform, "download_bytes", max(0, allowance - used), now)
    import io
    def playlist(url):
        stream = io.BytesIO()
        fetch(url, stream, playlist=True)
        return stream.getvalue().decode("utf-8")
    def attributes(value):
        return {key: quoted if quoted else plain for key, quoted, plain in
                re.findall(r'(?:^|,)([A-Z0-9-]+)=(?:"([^"]*)"|([^,]*))', value)}
    def segments(url, text):
        from .config import source_duration_limit
        if ("#EXTM3U" not in text or "#EXT-X-ENDLIST" not in text
                or re.search(r"#EXT-X-(?:KEY:(?!METHOD=NONE)|SESSION-KEY|BYTERANGE|DISCONTINUITY)", text)):
            raise AccessError("source HLS must be complete, unencrypted and independently readable")
        durations = [float(n) for n in re.findall(r"#EXTINF:([\d.]+)", text)]
        urls = [urljoin(url, line.strip()) for line in text.splitlines() if line.strip() and not line.startswith("#")]
        init = re.findall(r'#EXT-X-MAP:URI="([^"]+)"', text)
        if (not durations or len(durations) != len(urls) or len(urls) > 400
                or sum(durations) > source_duration_limit(cfg) + 2 or len(init) > 1):
            raise AccessError("source HLS exceeds bounded duration or segment structure")
        if init:
            urls.insert(0, urljoin(url, init[0]))
        return urls
    for url in plan.get("media", []):
        try:
            if ".m3u8" not in urlsplit(url).path:
                with destination.open("wb") as out:
                    fetch(url, out)
                if validate:
                    validate(destination)
                destination.chmod(0o444)
                return
            text = playlist(url)
            if "#EXTM3U" not in text or re.search(r"#EXT-X-(?:KEY:(?!METHOD=NONE)|SESSION-KEY)", text):
                raise AccessError("source HLS encryption or format is unsupported")
            audio_url = None
            variants = re.findall(r"#EXT-X-STREAM-INF:([^\n]+)\n([^#\n]+)", text)
            if variants:
                # RFC 8216 4.3.4.2: low-bandwidth variants may be audio-only;
                # AUDIO names an EXT-X-MEDIA group, not a video-track URL.
                def video_variant(pair):
                    attrs = attributes(pair[0])
                    codecs = attrs.get("CODECS", "").lower()
                    known = bool(attrs.get("RESOLUTION") or re.search(r"(?:^|,)(?:avc1|hvc1|hev1|vp09|vp9|av01)", codecs))
                    return known, bool(codecs and not known)
                variants = [pair for pair in variants if not video_variant(pair)[1]]
                if not variants:
                    raise AccessError("source HLS offers no video variant")
                variants.sort(key=lambda pair: (not video_variant(pair)[0], int(attributes(pair[0]).get("BANDWIDTH", "0"))))
                group = attributes(variants[0][0]).get("AUDIO")
                if group:
                    renditions = [attributes(line) for line in re.findall(r"#EXT-X-MEDIA:([^\n]+)", text)]
                    matched = [item for item in renditions if item.get("TYPE") == "AUDIO" and item.get("GROUP-ID") == group]
                    if not matched:
                        raise AccessError("source HLS audio group unavailable")
                    matched.sort(key=lambda item: item.get("DEFAULT") != "YES")
                    if matched[0].get("URI"):
                        audio_url = urljoin(url, matched[0]["URI"])
                url = urljoin(url, variants[0][1].strip())
                text = playlist(url)
            elif platform == "x" and x_resource_kind(url) == 2 and plan.get("audio_media"):
                # Both track URLs were observed for this exact native player.
                # Do not synthesize a missing master URL or infer another CDN.
                audio_url = plan["audio_media"]
            tracks = [segments(url, text)]
            if audio_url:
                tracks.append(segments(audio_url, playlist(audio_url)))
            with tempfile.TemporaryDirectory(prefix="native-source-", dir=destination.parent) as folder:
                inputs = []
                for i, track in enumerate(tracks):
                    joined = Path(folder) / f"source{i}.bin"
                    with joined.open("wb") as out:
                        for segment in track:
                            fetch(segment, out)
                    inputs += ["-protocol_whitelist", "file,pipe", "-i", str(joined)]
                audio_index = 1 if audio_url else 0
                media.ffmpeg([*inputs, "-map", "0:v:0", "-map", f"{audio_index}:a:0",
                              "-c", "copy", "-movflags", "+faststart", "-f", "mp4", str(destination)], cfg)
            if destination.stat().st_size > cfg.max_download_bytes:
                raise AccessError("source output exceeds file cap")
            if validate:
                validate(destination)
            destination.chmod(0o444)
            return
        except Deferred:
            destination.unlink(missing_ok=True)
            raise
        except (AccessError, OSError, ValueError):
            destination.unlink(missing_ok=True)
    raise AccessError("normal-page source media unavailable; refresh source page")
