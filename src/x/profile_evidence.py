"""Read an exact author's public profile counters, without likes or follows."""
import json
import re
import time

from . import safari


def count(raw):
    match = re.fullmatch(r"((?:\d{1,3}(?:[, \u00a0\u202f]\d{3})+|\d+)(?:\.\d+)?)\s*([KMB]?)", str(raw).strip(), re.I)
    if not match:
        return None
    value = float(re.sub(r"[, \u00a0\u202f]", "", match[1]))
    if not match[2] and not value.is_integer():
        return None
    value *= {"": 1, "k": 1000, "m": 1000000, "b": 1000000000}[match[2].lower()]
    return int(value) if 0 <= value <= 2**53 - 1 else None


def read(handle):
    handle = handle.lower().lstrip("@")
    if not re.fullmatch(r"[a-z0-9_]{1,15}", handle):
        return {}
    with safari._safari_lock:
        try:
            if not safari.open_url("https://x.com/" + handle):
                return {}
            time.sleep(3)
            script = r"""(() => {
              const handle = __HANDLE__;
              if (!['x.com','www.x.com','twitter.com','www.twitter.com'].includes(location.hostname)
                || location.pathname.toLowerCase().replace(/\/$/,'') !== '/' + handle) return '{}';
              const primary = document.querySelector('[data-testid="primaryColumn"]');
              if (!primary || !primary.querySelector('[data-testid="UserName"]')) return '{}';
              const links = [...primary.querySelectorAll('a[href]')].filter(a =>
                !a.closest('article') && ['/'+handle+'/followers','/'+handle+'/verified_followers']
                  .includes(a.pathname.toLowerCase().replace(/\/$/,'')));
              if (!links.length) return '{}';
              const values = links.map(a => (a.textContent || '').trim()
                .replace(/\s+(?:Followers|Abonnés)$/i,'').trim());
              if (new Set(values).size !== 1) return '{}';
              return JSON.stringify({handle, followers: values[0],
                bio: primary.querySelector('[data-testid="UserDescription"]')?.innerText || ''});
            })()""".replace("__HANDLE__", json.dumps(handle))
            try:
                data = json.loads(safari._run_js(script, 10, log_prefix="[AUDIENCE]") or "{}")
            except (TypeError, ValueError):
                return {}
            if not isinstance(data, dict) or data.get("handle") != handle:
                return {}
            data["followers"] = count(data.get("followers"))
            data["observed_at"] = time.time()
            return data
        finally:
            safari.close_front_tab()
