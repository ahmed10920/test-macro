from collections import Counter
import ctypes
import functools
import glob
import http.server
import io
import itertools
import json
import os
import queue
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
import webbrowser

HERE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
if HERE_DIR not in sys.path:
    sys.path.insert(0, HERE_DIR)
LOCAL_DEPS = os.path.join(HERE_DIR, 'deps')
if os.path.isdir(LOCAL_DEPS) and LOCAL_DEPS not in sys.path:
    sys.path.insert(0, LOCAL_DEPS)
if os.path.isdir(r'D:\mmacro_deps') and r'D:\mmacro_deps' not in sys.path:
    sys.path.insert(0, r'D:\mmacro_deps')

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')      # numpy reserves memory per core; low-RAM PCs fail to open


def dpi_aware():
    """Real pixels on every monitor. Must run before any window exists."""
    for aware in (lambda: ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)),
                  lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0,
                  lambda: ctypes.windll.user32.SetProcessDPIAware()):
        try:
            if aware():
                return
        except (AttributeError, OSError):
            pass


dpi_aware()

try:
    from pynput import keyboard  # noqa: E402
    from PIL import Image  # noqa: E402
    import webview  # noqa: E402
    import game  # noqa: E402
    import eden  # noqa: E402
    import fishing  # noqa: E402
    import merchant as shop  # noqa: E402
    import points  # noqa: E402
    import clipper  # noqa: E402
    import equip  # noqa: E402
    import selector  # noqa: E402
    import potions  # noqa: E402
    import merchant_cache  # noqa: E402
    from calibrator_ui import ToastService  # noqa: E402
except Exception as e:          # numpy's DLLs raise OSError, not ImportError
    why = str(e).strip().splitlines()[-1] if str(e).strip() else type(e).__name__
    try:
        folder = os.path.join(os.getenv('LOCALAPPDATA') or os.path.expanduser('~'), 'MMacroHUD')
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, 'startup_error.txt'), 'w', encoding='utf-8') as f:
            f.write('%s\n\nexe: %s\n' % (e, sys.executable))
    except OSError:
        pass
    ctypes.windll.user32.MessageBoxW(0, 'The macro could not load one of its own files.\n\n%s\n\n'
                                     'Most often an antivirus removed it, or the PC is out of memory:\n'
                                     '  - add the macro to your antivirus exclusions and download it again\n'
                                     '  - close other programs, then open it again\n%s\n'
                                     'Send this message to Manas if it keeps happening.'
                                     % (why, '  - on Windows N or KN, install the Media Feature Pack (Settings > Apps '
                                        '> Optional features)\n' if 'DLL load failed' in why else ''),
                                     'MMacro', 0x10)
    sys.exit(1)

TEXT = '#f1f5f9'
DIM = '#58677a'
ACCENT = '#38bdf8'
GOOD = '#22d3ee'
WARN = '#fbbf24'
BAD = '#f87171'

BIOMES_DIR = os.path.join(HERE_DIR, 'biomes')
os.makedirs(BIOMES_DIR, exist_ok=True)

TITLE = 'MMacro HUD'
VERSION = '1.1.4'
RELEASE_PAGE = 'https://github.com/ManasAarohi1/MMacro/releases/latest'
RELEASES = os.environ.get('MMACRO_UPDATE_URL') or 'https://api.github.com/repos/ManasAarohi1/MMacro/releases/latest'
INVITE = 'https://discord.gg/oppression'
ITEM_EVERY_S = {game.SC: 20 * 60, game.BR: 35 * 60}
ITEM_RETRY_S = 5 * 60
ITEM_SPARE_S = 15
RUNE = 'cursed rune fragment'
RUNE_BIOMES = ('PUMPKIN MOON', 'GRAVEYARD')
RUNE_TRIES, RUNE_RETRY_S = 2, 60
SELECTOR_RETRY_S = 5 * 60
POP_BIOMES = ('GLITCHED', 'DREAMSPACE', 'CYBERSPACE')
HOLD_BIOMES = ('GLITCHED', 'DREAMSPACE', 'CYBERSPACE', 'THE RADIANT FOREST', 'SINGULARITY', 'BLOOD RAIN',
               'GRAVEYARD', 'PUMPKIN MOON')
SELECTOR_REFUSED_S = 11 * 60
SELECTOR_REFUSALS = 3
SELECTOR_MISSES = 3
REJOIN_WAITS = (15, 30, 60)
IN_GAME_S = 150
OUT_S = 180
PLAY_EVERY_S = 20
STALL_S = 600
SLEPT_S = 60
WATCH_EVERY = 0.5
CRASH_WAITS = (30, 60, 120, 300)
LOOK_EVERY_S = 1.5
AFK_EVERY_S = 300
EDEN_RETRY_S = 60
EDEN_GIVE_UP_S = 30 * 60
EDEN_AFK_REST_S = 900
CRACK = 'portable crack'
CRACK_S = 3.0
EQUIP_RETRY_S = 5 * 60
JOIN_NONE_S = 300
EQUIP_GAP_S = 90
MERCHANT_STALE_S = 150
LATE_RESULT_S = 8
DAILY_UTC_S = 22 * 3600 + 60
DAILY_LATE_S = 90
STRAY_EVERY_S = 20
MERCHANT_REPEAT_S = 600
BOSS_BIOMES = {'Boss': 'GRAVEYARD', 'Sinister P.': 'PUMPKIN MOON'}
BOSS_EARLY_S = 5
MERCHANT_TRIES = 3

LOG_MAX = 4 << 20

_log_lock = threading.Lock()
_recent_logs = []


def note(tag, msg):
    """Append a line to logs.txt; never raises."""
    with _log_lock:
        _note(tag, msg)


def _note(tag, msg):
    ts = time.strftime('%H:%M:%S')
    _recent_logs.append((ts, tag, str(msg)))
    if len(_recent_logs) > 400:
        del _recent_logs[:100]
    try:
        os.makedirs(game.APP_DIR, exist_ok=True)
        path = os.path.join(game.APP_DIR, 'logs.txt')
        if os.path.exists(path) and os.path.getsize(path) > LOG_MAX:
            with open(path, 'rb') as f:
                f.seek(-LOG_MAX // 2, os.SEEK_END)
                tail = f.read().split(b'\n', 1)[-1]
            with open(path, 'wb') as f:
                f.write(tail)
        with open(path, 'a', encoding='utf-8') as f:
            f.write('%s  [%s] %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), tag, msg))
    except OSError:
        pass


CACHE_UNREADABLE = ('Roblox\'s cache (rbx-storage.db) could not be read, so merchants and the boss are not seen. Close '
                    'Roblox, delete the rbx-storage.db files in %LOCALAPPDATA%\\Roblox (Roblox makes them again) and '
                    'open Roblox normally, not as administrator.')
STORE_ROBLOX = ('Merchant detection reads Roblox\'s cache (rbx-storage.db), which was not found on this PC. It works '
                'with Roblox from roblox.com, Bloxstrap or Fishstrap.\n\nOpen Roblox once, or leave Merchant detection '
                'off.')


class _ToLog:
    """The windowed exe has no console, so print goes to logs.txt."""

    def __init__(self):
        self.buf = ''

    def write(self, s):
        self.buf += s
        while '\n' in self.buf:
            line, self.buf = self.buf.split('\n', 1)
            if line.strip():
                note('out', line.strip())

    def flush(self):
        pass


if sys.stdout is None or type(sys.stdout).__name__ == 'NullWriter':
    sys.stdout = sys.stderr = _ToLog()


def clip_floor(text):
    """'from 1 in' as a number; junk means 1 in a billion, never every roll."""
    try:
        return max(1, int(float(re.sub(r'[,\s_]', '', text or ''))))
    except (ValueError, OverflowError):
        return 1_000_000_000


def device_line():
    """PC info for bug reports; never raises."""
    try:
        import platform
        u = ctypes.windll.user32
        w = game.find_roblox_window()
        client = 'no Roblox window'
        if w is not None:
            x, y, cw, ch = game.client_rect(w)
            s = game.window_scale(w)
            client = '%dx%d at %d,%d (%s%s)' % (cw, ch, x, y, game.awareness(w.hwnd), '' if s == 1 else
                                               ', laid out at %dx%d, stretched %d%% by Windows'
                                               % (round(cw / s), round(ch / s), round(s * 100)))
        dpi = u.GetDpiForWindow(w.hwnd) if w is not None else 0
        return ('v%s, Windows %s, screen %dx%d (all %dx%d), Roblox client %s, scale %d%%%s, MMacro %s%s%s'
                % (VERSION, platform.version(), u.GetSystemMetrics(0), u.GetSystemMetrics(1), u.GetSystemMetrics(78),
                   u.GetSystemMetrics(79), client, round(dpi * 100 / 96), game.in_dpi(game.REAL, display_line, w),
                   game.awareness(), '' if u.IsProcessDPIAware() else ' (a compatibility setting on the exe?)',
                   ', mouse buttons swapped' if u.GetSystemMetrics(23) else ''))
    except Exception as e:
        return 'v%s, device not read: %s: %s' % (VERSION, type(e).__name__, e)


def display_line(w):
    """Real monitor resolution and scale, outside our own DPI view."""
    try:
        u, g = ctypes.WinDLL('user32'), ctypes.WinDLL('gdi32')
        u.GetDC.restype = u.MonitorFromWindow.restype = ctypes.c_void_p
        u.GetDC.argtypes, u.ReleaseDC.argtypes = [ctypes.c_void_p], [ctypes.c_void_p, ctypes.c_void_p]
        g.GetDeviceCaps.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        hdc = u.GetDC(None)
        real = '%dx%d' % (g.GetDeviceCaps(hdc, 118), g.GetDeviceCaps(hdc, 117))
        u.ReleaseDC(None, hdc)
        mon = u.MonitorFromWindow(w.hwnd if w is not None else None, 2)
        x, y = ctypes.c_uint(), ctypes.c_uint()
        ctypes.windll.shcore.GetDpiForMonitor(ctypes.c_void_p(mon), 0, ctypes.byref(x), ctypes.byref(y))
        return ' (display %s, monitor scale %d%%%s)' % (real, round(x.value * 100 / 96),
                                                        ', remote desktop' if u.GetSystemMetrics(0x1000) else '')
    except Exception as e:
        return ' (display not read: %s)' % type(e).__name__


# ================================================================ Discord & Biomes
FOOTER = 'Join Manas Biome Support/Hunt Server'
TESTERS = ('Forsakened One', 'Daniel', 'Slpxy', 'Nova', 'imsomeone', 'Evil Talin Siran', 'ghost', '███\'█_Guest',
           'delta_likes_cats_xd')
EMBED_GOOD, EMBED_BAD, EMBED_INFO, EMBED_BIOME, EMBED_GOLD = 0x57F287, 0xED4245, 0x8A8F98, 0x58B9FF, 0xFFD700
BIOME_COLOURS = {'NORMAL': 0x4A90E2, 'WINDY': 0x7ED6DF, 'RAINY': 0x3898EC, 'SNOWY': 0xA8D8FF, 'SAND STORM': 0xE0A85A,
                 'HELL': 0xE74C3C, 'STARFALL': 0x6C7BFF, 'CORRUPTION': 0x9B59B6, 'NULL': 0x64748B, 'HEAVEN': 0xFCD34D,
                 'LOST FOREST': 0x2ECC71, 'GLITCHED': 0x3BE37A, 'DREAMSPACE': 0xE86AF0, 'CYBERSPACE': 0x2FD3FF,
                 'SINGULARITY': 0x6D28D9, 'THE RADIANT FOREST': 0xFDE047,
                 'GRAVEYARD': 0x6B7280, 'PUMPKIN MOON': 0xF97316, 'BLOOD RAIN': 0xDC2626}

BIOME_RATES = {
    'NORMAL': '1/1/sec',
    'WINDY': '1/500/sec',
    'SNOWY': '1/600/sec',
    'RAINY': '1/750/sec',
    'SAND STORM': '1/3,000/sec',
    'HELL': '1/6,666/sec',
    'STARFALL': '1/7,500/sec',
    'HEAVEN': '1/9,000/sec',
    'CORRUPTION': '1/9,000/sec',
    'NULL': '1/13,333/sec',
    'GLITCHED': '1/30,000/sec',
    'DREAMSPACE': '1/5,000,000/sec',
    'CYBERSPACE': '1/1,000,000/sec',
    'LOST FOREST': '1/15,000/sec',
    'SINGULARITY': 'Event Biome',
    'THE RADIANT FOREST': 'Event Biome',
    'GRAVEYARD': 'Event Biome',
    'PUMPKIN MOON': 'Event Biome',
    'BLOOD RAIN': 'Event Biome',
}

PING = {'GLITCH', 'GLITCHED', 'DREAMSPACE', 'CYBERSPACE'}
CLIP_COLOURS = ((10 ** 10, 0xFFC94D), (10 ** 9, 0xB38CFF), (10 ** 8, 0x58B9FF), (1, EMBED_GOOD))
MERCHANT_COLOURS = {'Rin': 0xFF8C00, 'Mari': 0xFFD700, 'Jester': 0x9B59B6, 'Boss': 0x6A0DAD, 'Sinister P.': 0x6A0DAD}


def base_biome(name):
    """Event biomes may come as '(Event) Graveyard'."""
    return re.sub(r'^\W*EVENT\W*', '', (name or '').upper()).strip()


def biome_colour(name):
    return BIOME_COLOURS.get(base_biome(name), EMBED_BIOME)


def biome_rgb(name):
    c = biome_colour(name)
    return ((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF)


def biome_slug(name):
    return re.sub(r'[^a-z0-9]+', '_', base_biome(name).lower()).strip('_')


def find_biome_photo(name):
    """Return path to custom biome photo in `biomes/` folder if present, else None."""
    slug = biome_slug(name)
    if not slug:
        return None
    for ext in ('.png', '.jpg', '.jpeg', '.webp', '.bmp'):
        for cand in (slug + ext, slug.replace('_', '') + ext, slug.replace('_', ' ') + ext):
            p = os.path.join(BIOMES_DIR, cand)
            if os.path.isfile(p):
                return p
    return None


def biome_web_path(name):
    """Return URL path rooted at HERE_DIR for the WebView UI."""
    p = find_biome_photo(name)
    if p:
        rel = os.path.relpath(p, HERE_DIR).replace('\\', '/')
        return '/' + rel
    return '/biomes/normal.png'


def biome_png(name):
    """PNG bytes of the biome photo for Discord webhook embeds, or None."""
    path = find_biome_photo(name)
    if not path:
        return None
    try:
        with open(path, 'rb') as f:
            data = f.read()
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            return data
        buf = io.BytesIO()
        Image.open(io.BytesIO(data)).convert('RGBA').save(buf, 'PNG')
        return buf.getvalue()
    except Exception:
        return None


def next_daily(now=None):
    """Next 22:01 GMT in epoch seconds; any time zone."""
    now = time.time() if now is None else now
    t = now // 86400 * 86400 + DAILY_UTC_S
    return t if t > now else t + 86400


def rune_biome(name, picked):
    """The picked biome `name` is, or None."""
    squashed = base_biome(name).replace(' ', '')
    return next((b for b in picked if b.replace(' ', '') == squashed), None)


def is_rare(name):
    squashed = (name or '').upper().replace(' ', '')
    return any(p in squashed for p in PING)


class BiomeWatcher:
    """Tracks biome changes; rare ones alert once per cooldown, even at start."""

    def __init__(self, cooldown=300.0):
        self.cooldown = cooldown
        self.current = None
        self._last_alert = {}

    def feed(self, name, now=None):
        """(biome, alert) on a change, else None."""
        if not name:
            return None
        name = name.upper()
        if name == self.current:
            return None
        now = time.time() if now is None else now
        self.current = name
        last = self._last_alert.get(name)
        alert = is_rare(name) and (last is None or now - last >= self.cooldown)
        if alert:
            self._last_alert[name] = now
        return name, alert


def pretty(name):
    return ' '.join(w.capitalize() for w in (name or '').split())


def clean_url(text):
    return ''.join((text or '').split())


def _build_webhook_request(webhook_url, payload, files=None):
    """Build a urllib Request for JSON or multipart Discord webhook delivery."""
    if not files:
        body, kind = json.dumps(payload).encode('utf-8'), 'application/json'
    else:
        b = uuid.uuid4().hex
        body = ('--%s\r\nContent-Disposition: form-data; name="payload_json"\r\n'
                'Content-Type: application/json\r\n\r\n%s\r\n' % (b, json.dumps(payload))).encode('utf-8')
        for i, (name, png) in enumerate(files.items()):
            body += ('--%s\r\nContent-Disposition: form-data; name="files[%d]"; filename="%s"\r\n'
                     'Content-Type: image/png\r\n\r\n' % (b, i, name)).encode('utf-8') + png + b'\r\n'
        body += ('--%s--\r\n' % b).encode('utf-8')
        kind = 'multipart/form-data; boundary=' + b
    return urllib.request.Request(webhook_url, data=body,
                                  headers={'Content-Type': kind, 'User-Agent': 'SolsBiomeLogger/1.0'})


def _post(webhook_url, payload, files=None, on_error=None):
    """Posts on a thread; `files` {name: png} go as attachment://name."""
    err_cb = on_error or (lambda m: note('webhook', m))

    def run():
        try:
            req = _build_webhook_request(webhook_url, payload, files)
            urllib.request.urlopen(req, timeout=30).close()
        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = e.read().decode('utf-8', errors='replace')[:200]
            except Exception:
                pass
            err_cb('webhook HTTP %s: %s %s' % (e.code, e.reason, detail))
        except (urllib.error.URLError, OSError, ValueError) as e:
            err_cb('webhook failed: %s: %s' % (type(e).__name__, e))
    threading.Thread(target=run, daemon=True).start()


def _timestamp():
    return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())


_logo = []


def logo_png():
    if not _logo:
        try:
            with open(os.path.join(HERE_DIR, 'axolotl.png'), 'rb') as f:
                _logo.append(f.read())
        except OSError:
            _logo.append(None)
    return _logo[0]


def server_field(link):
    link = (link or '').strip()
    if not link:
        return 'No private server inserted'
    if link.startswith(('https://', 'http://')) and ' ' not in link:
        return '[Join](%s)' % link[:900]
    return link[:1000]


def post_event(webhook_url, title, description='', colour=EMBED_INFO, area='Macro', fields=(), ping='', shot=None,
               footer=True, thumb=None):
    if not webhook_url:
        return
    embed = {'author': {'name': 'MMacro · %s' % area, 'url': INVITE}, 'title': title[:256], 'color': colour,
             'timestamp': _timestamp()}
    files = {}
    if logo_png():
        files['logo.png'] = logo_png()
        embed['author']['icon_url'] = 'attachment://logo.png'
    if description:
        embed['description'] = description[:4000]
    if footer:
        fields = list(fields) + [('​', '-# [%s](%s)' % (FOOTER, INVITE), False)]
    if fields:
        embed['fields'] = [{'name': n, 'value': str(v)[:1024] or '-', 'inline': i} for n, v, i in fields]
    if thumb:
        files['biome.png'] = thumb
        embed['thumbnail'] = {'url': 'attachment://biome.png'}
    if shot:
        files['shot.png'] = shot
        embed['image'] = {'url': 'attachment://shot.png'}
    _post(webhook_url, {'content': ping, 'embeds': [embed]}, files)


def capital(text):
    text = text or ''
    return text[:1].upper() + text[1:]


def mention(user_id):
    user_id = ''.join(c for c in user_id or '' if c.isdigit())
    return '<@%s>' % user_id if user_id else ''


def span(seconds):
    m = int(max(0, seconds)) // 60
    return '%dh %dm' % divmod(m, 60) if m >= 60 else '%dm' % m if m else '<1m'


def post_biome(webhook_url, name, ping=True, server='', running=None, here=None, sync=False):
    """Posts a Biome Started embed with right-side biome emblem and @everyone rare pings."""
    if not webhook_url:
        return
    now_ts = int(time.time())
    srv = (server or '').strip() or 'No private server inserted'
    fields = [{'name': 'Private Server', 'value': srv[:1024], 'inline': False}]
    if running is not None:
        fields += [
            {'name': 'Running', 'value': span(running), 'inline': True},
            {'name': 'This server', 'value': span(here), 'inline': True},
        ]
    embed = {
        'title': 'Biome Started - %s' % base_biome(name),
        'description': '<t:%d:T> (<t:%d:R>)' % (now_ts, now_ts),
        'color': biome_colour(name),
        'fields': fields,
        'footer': {'text': '%s | Release v%s' % (TITLE, VERSION)},
    }
    files = {}
    thumb = biome_png(name)
    if thumb:
        files['biome.png'] = thumb
        embed['thumbnail'] = {'url': 'attachment://biome.png'}
    do_ping = bool(ping) or is_rare(name)
    payload = {
        'content': '@everyone' if do_ping else '',
        'allowed_mentions': {'parse': ['everyone']} if do_ping else {'parse': []},
        'embeds': [embed],
    }
    if sync:
        urllib.request.urlopen(_build_webhook_request(webhook_url, payload, files), timeout=30).close()
    else:
        _post(webhook_url, payload, files)


def post_merchant(webhook_url, name, server=''):
    title = {'Boss': 'Sinister S. has spawned', 'Sinister P.': 'Sinister P. has spawned'}.get(
        name, 'Merchant Arrived - %s' % name)
    post_event(webhook_url, title, 'Found <t:%d:R>' % time.time(),
               MERCHANT_COLOURS.get(name, EMBED_GOLD), 'Merchant', [('Private server', server_field(server), True)],
               footer=False)


def post_shot(webhook_url, title, colour, ping='', detail='', area='Macro', fields=()):
    if not webhook_url:
        return
    buf = io.BytesIO()
    Image.fromarray(game.grab(game.client_box((0.0, 0.0, 1.0, 1.0)))).save(buf, 'PNG')
    post_event(webhook_url, title, detail, colour, area, fields, mention(ping), buf.getvalue())


def append_history(biome):
    try:
        os.makedirs(os.path.dirname(game.HISTORY_FILE), exist_ok=True)
        with open(game.HISTORY_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'ts': time.time(), 'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'biome': biome}) + '\n')
    except OSError:
        pass


# ================================================================ HTTP Server & Roblox Profile
COUNTS_ORDER = (
    'GLITCHED', 'DREAMSPACE', 'CYBERSPACE', 'WINDY', 'RAINY',
    'SNOWY', 'SAND STORM', 'HELL', 'HEAVEN', 'STARFALL',
    'CORRUPTION', 'NULL', 'LOST FOREST', 'GRAVEYARD', 'PUMPKIN MOON',
    'BLOOD RAIN', 'SINGULARITY', 'THE RADIANT FOREST', 'NORMAL',
)


def detect_roblox_profile():
    """Return (username, userid) from Roblox LocalStorage or latest log."""
    local = os.getenv('LOCALAPPDATA') or ''
    app_stor = os.path.join(local, 'Roblox', 'LocalStorage', 'appStorage.json')
    uname, uid = None, None
    try:
        if os.path.isfile(app_stor):
            with open(app_stor, encoding='utf-8', errors='replace') as f:
                data = json.load(f)
            raw_u = str(data.get('Username') or '').strip()
            raw_id = str(data.get('UserId') or '').strip()
            if raw_u:
                uname = raw_u
            if raw_id.isdigit() and int(raw_id) > 0:
                uid = raw_id
    except Exception:
        pass
    if not uid:
        try:
            latest = game.newest_log()
            if latest and os.path.isfile(latest):
                with open(latest, encoding='utf-8', errors='replace') as f:
                    m = re.search(r'userid[:=]\s*(\d+)', f.read(65536), re.I)
                    if m:
                        uid = m.group(1)
        except Exception:
            pass
    return uname or os.environ.get('USERNAME') or 'Player', uid or ''


def resolve_avatar_file(uid=''):
    """Return path to cached/custom Roblox avatar PNG, or brand logo."""
    candidates = [os.path.join(game.APP_DIR, 'avatar_custom.png')]
    if uid:
        candidates.append(os.path.join(game.APP_DIR, 'avatar_%s.png' % uid))
    candidates.extend([
        os.path.join(game.APP_DIR, 'avatar.png'),
        os.path.join(HERE_DIR, 'ui', 'brand_logo.png'),
        os.path.join(HERE_DIR, 'axolotl.png'),
    ])
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None


def seed_and_refresh_avatar(uid, on_ready=None, stop_fn=None, sync=False):
    """Fetch true Roblox user avatar (synchronously if sync=True, or in background with retry)."""
    if not uid:
        return
    dst = os.path.join(game.APP_DIR, 'avatar_%s.png' % uid)

    def _try_once():
        urls = (
            'https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds=%s&size=150x150&format=Png&isCircular=false' % uid,
            'https://thumbnails.roproxy.com/v1/users/avatar-headshot?userIds=%s&size=150x150&format=Png&isCircular=false' % uid,
        )
        for api_url in urls:
            try:
                req = urllib.request.Request(api_url, headers={'User-Agent': 'MMacroHUD/1.0'})
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = json.load(r)
                items = data.get('data') or []
                img_url = items[0].get('imageUrl') if items else None
                if not img_url:
                    continue
                img_req = urllib.request.Request(img_url, headers={'User-Agent': 'MMacroHUD/1.0'})
                with urllib.request.urlopen(img_req, timeout=10) as ir:
                    raw = ir.read()
                if raw.startswith(b'\x89PNG'):
                    os.makedirs(game.APP_DIR, exist_ok=True)
                    with open(dst, 'wb') as out:
                        out.write(raw)
                    if on_ready:
                        on_ready()
                    return True
            except Exception as e:
                note('ui', 'avatar fetch failed (%s): %s: %s' % (uid, type(e).__name__, e))
                continue
        return False

    def _run():
        if _try_once():
            return
        while not (stop_fn and stop_fn()):
            time.sleep(15)
            if stop_fn and stop_fn():
                return
            if _try_once():
                return

    if sync:
        if _try_once():
            return
    threading.Thread(target=_run, daemon=True).start()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    avatar_uid = ''

    def do_GET(self):
        clean_path = self.path.split('?', 1)[0]
        if clean_path == '/avatar.png':
            fpath = resolve_avatar_file(self.avatar_uid)
            if fpath:
                try:
                    with open(fpath, 'rb') as f:
                        raw = f.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'image/png')
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                except OSError:
                    pass
        super().do_GET()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, must-revalidate')
        super().end_headers()

    def log_message(self, format, *args):
        pass


class _ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def start_ui_server(avatar_uid=''):
    _QuietHandler.avatar_uid = avatar_uid or ''
    handler = functools.partial(_QuietHandler, directory=HERE_DIR)
    srv = _ThreadingServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _find_own_hwnd(title=TITLE):
    u32 = ctypes.windll.user32
    me = os.getpid()
    found = []

    def cb(h, _):
        pid = ctypes.c_ulong()
        u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == me and u32.IsWindowVisible(h):
            n = u32.GetWindowTextLengthW(h)
            if n > 0:
                found.append(h)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else u32.FindWindowW(None, title)


def _set_hwnd_topmost(hwnd, on_top):
    if not hwnd:
        return False
    u32 = ctypes.WinDLL('user32', use_last_error=True)
    u32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    u32.SetWindowPos.restype = ctypes.c_bool
    insert_after = ctypes.c_void_p(-1 if on_top else -2)
    return bool(u32.SetWindowPos(ctypes.c_void_p(hwnd), insert_after, 0, 0, 0, 0, 0x0013))


def _dark_titlebar_hwnd(hwnd):
    if not hwnd:
        return
    try:
        val = ctypes.c_int(1)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), attr, ctypes.byref(val), ctypes.sizeof(val)
            )
    except Exception:
        pass


def normalize_cfg(raw):
    cfg = dict(game.DEFAULTS)
    if isinstance(raw, dict):
        cfg.update(raw)
    cfg.setdefault('rune_on', False)
    cfg.setdefault('rune_biomes', list(RUNE_BIOMES))
    cfg.setdefault('rune_after', 0)
    cfg.setdefault('selector_on', False)
    cfg.setdefault('selector_biome', 'HEAVEN')
    cfg.setdefault('pop_on', False)
    cfg.setdefault('pop_items', {})
    cfg.setdefault('clip_key_on', False)
    cfg.setdefault('clip_keys', 'Win+Alt+G')
    cfg.setdefault('equip_on', False)
    cfg.setdefault('equip_aura', '')
    cfg.setdefault('roblox_username', '')
    cfg.setdefault('roblox_uid', '')
    cfg.setdefault('tutorial_seen', False)
    cfg.setdefault('collect_merchants', ['Jester', 'Mari', 'Rin'])
    if not isinstance(cfg.get('buy_items'), dict):
        cfg['buy_items'] = {}
    if not isinstance(cfg.get('pop_items'), dict):
        cfg['pop_items'] = {}
    if not isinstance(cfg.get('rune_biomes'), list):
        cfg['rune_biomes'] = list(RUNE_BIOMES)
    if not isinstance(cfg.get('collect_merchants'), list):
        cfg['collect_merchants'] = ['Jester', 'Mari', 'Rin']
    return cfg


# ================================================================ Automation Engine & WebView API
class MacroEngine:
    def __init__(self):
        self.running = False
        self.phase_text = 'idle'
        self.biome_stop = None
        self._last_hotkey = {}
        self._closing = False
        self._capturing = False
        self.url = ''
        self.use_items = False
        self.server_link = ''
        self.reconnect_on = False
        self.browser_rejoin = False
        self.slow_pc = False
        self.need_rejoin = None
        self.start_again = False
        self.item_due = {}
        self._key_stop = False
        self.played = False
        self.rune_biomes, self.rune_wait, self.rune_due, self.rune_tries = set(), 0, None, 0
        self.selector_biome, self.selector_due, self.selector_refused, self.selector_missed = None, None, 0, 0
        self.pop_biomes, self.pop_due, self.pop_list = set(), None, {}
        self.pop_left = None
        self.rejoining = False
        self.watch = None
        self.merchant_detect = False
        self.block_on = False
        self.blocked = {}
        self.block_path = None
        self.block_lock = threading.Lock()
        self.got_past_block = False
        self.merchant_due = None
        self.merchant_at = 0.0
        self._merchant_posted = {}
        self._boss_seen = {}
        self.collect = False
        self.wanted = {}
        self.collect_names = set()
        self.clipper = None
        self.clip_min = 0
        self.equip_aura = None
        self.crack_on = False
        self.in_dimension = True
        self.equip_due = None
        self.equip_busy_at = 0.0
        self.aura_logged = (None, 0.0)
        self.run_wall = 0.0
        self.equip_fails = 0
        self.joined_at = 0.0
        self.biome_now = 'NORMAL'
        self.rares_count = 0
        self.cfg = normalize_cfg(game.load_settings())
        auto_name, auto_uid = detect_roblox_profile()
        custom_name = self.cfg_str('roblox_username').strip()
        cached_uid = self.cfg_str('roblox_uid').strip()
        self.player_name = custom_name or auto_name
        if not custom_name or custom_name.lower() == auto_name.lower():
            self.roblox_uid = auto_uid
        else:
            self.roblox_uid = cached_uid
        _QuietHandler.avatar_uid = self.roblox_uid
        if custom_name and not self.roblox_uid:
            self._resolve_uid_and_avatar(custom_name, sync=False)
        self.fisher = None
        self.out_since = None
        self._look_at = self._played = 0.0
        self.beat = time.monotonic()
        self.restart_run = False
        self.run_id = 0
        self.cache_bust = 1
        self._history = []
        self._biome_counts = Counter()
        self._lock = threading.RLock()
        self._window = None
        self._toast = ToastService()

        self.block_on = bool(self.cfg.get('merchant_on'))
        self.wanted = self.wanted_items()
        self.pop_list = self.pop_items()

        try:
            if os.path.exists(game.HISTORY_FILE):
                with open(game.HISTORY_FILE, 'r', encoding='utf-8', errors='replace') as f:
                    all_rows = []
                    for line in f:
                        s = line.strip()
                        if not s:
                            continue
                        try:
                            item = json.loads(s)
                        except Exception:
                            continue
                        b = base_biome(item.get('biome') or 'NORMAL') or 'NORMAL'
                        self._biome_counts[b] += 1
                        all_rows.append(item)
                for item in all_rows[-50:]:
                    b = (item.get('biome') or 'NORMAL').upper()
                    t_full = item.get('time', '')
                    t_short = t_full.split(' ')[-1] if ' ' in t_full else (t_full or '--:--:--')
                    self._history.append({'biome': b, 'time': t_short})
                if all_rows:
                    self.biome_now = (all_rows[-1].get('biome') or 'NORMAL').upper()
                self.rares_count = sum(v for k, v in self._biome_counts.items() if is_rare(k))
        except Exception:
            pass
        self._sync_live_roblox_log(initial=True)
        seed_and_refresh_avatar(self.roblox_uid, on_ready=self._bump_cache_bust, stop_fn=lambda: self._closing)

        self.cache = merchant_cache.Tracker()
        self._keyboard = keyboard
        threading.Thread(target=self._watch_cache, daemon=True).start()
        threading.Thread(target=self._poll_hotkeys, daemon=True).start()
        threading.Thread(target=self._poll_live_telemetry, daemon=True).start()
        threading.Thread(target=self._autosave_loop, daemon=True).start()
        threading.Thread(target=self._fetch_auras, daemon=True).start()

    def _autosave_loop(self):
        last_snap = None
        while not self._closing:
            time.sleep(10)
            if self._closing:
                break
            try:
                snap = json.dumps(self.cfg, sort_keys=True)
                if snap != last_snap:
                    self.remember()
                    last_snap = snap
            except Exception:
                pass

    def _bump_cache_bust(self):
        with self._lock:
            self.cache_bust += 1

    def _resolve_uid_and_avatar(self, username, sync=False):
        def _work():
            body = json.dumps({'usernames': [username], 'excludeBannedUsers': False}).encode('utf-8')
            for url in ('https://users.roblox.com/v1/usernames/users',
                        'https://users.roproxy.com/v1/usernames/users'):
                try:
                    req = urllib.request.Request(
                        url, data=body,
                        headers={'Content-Type': 'application/json', 'User-Agent': 'MMacroHUD/1.0'},
                    )
                    with urllib.request.urlopen(req, timeout=6) as r:
                        rows = (json.load(r) or {}).get('data') or []
                    if rows and rows[0].get('id'):
                        uid = str(rows[0]['id'])
                        with self._lock:
                            self.roblox_uid = uid
                            self.cfg['roblox_uid'] = uid
                            _QuietHandler.avatar_uid = uid
                            self.cache_bust += 1
                        self.remember()
                        seed_and_refresh_avatar(uid, on_ready=self._bump_cache_bust, stop_fn=lambda: self._closing, sync=sync)
                        return uid
                except Exception:
                    continue
            return ''

        if sync:
            return _work()
        threading.Thread(target=_work, daemon=True).start()
        return ''

    def apply_roblox_username(self, raw_name, sync=False):
        name = (raw_name or '').strip()
        auto_name, auto_uid = detect_roblox_profile()
        custom_av = os.path.join(game.APP_DIR, 'avatar_custom.png')
        if os.path.isfile(custom_av):
            try:
                os.remove(custom_av)
            except OSError:
                pass
        with self._lock:
            self.cfg['roblox_username'] = name
            self.player_name = name or auto_name
            if not name or name.lower() == auto_name.lower():
                self.roblox_uid = auto_uid
                self.cfg['roblox_uid'] = auto_uid
                _QuietHandler.avatar_uid = auto_uid
                seed_and_refresh_avatar(auto_uid, on_ready=self._bump_cache_bust, stop_fn=lambda: self._closing, sync=sync)
            else:
                self.roblox_uid = ''
                self.cfg['roblox_uid'] = ''
                _QuietHandler.avatar_uid = ''
                self.cache_bust += 1
        self.remember()
        if name and name.lower() != auto_name.lower():
            self._resolve_uid_and_avatar(name, sync=sync)

    def _fetch_auras(self):
        try:
            note('clip', 'aura list from GitHub: %d auras' % clipper.refresh())
        except Exception as e:
            note('clip', 'aura list not fetched, using the saved one: %s: %s' % (type(e).__name__, e))

    # --------------------------------------------------------------- Config helpers
    def cfg_bool(self, key, default=False):
        return bool(self.cfg.get(key, default))

    def cfg_str(self, key, default=''):
        val = self.cfg.get(key, default)
        return '' if val is None else str(val)

    def cfg_int(self, key, default=0, min_val=0):
        try:
            return max(min_val, int(str(self.cfg.get(key, default) or default).strip() or default))
        except (ValueError, TypeError):
            return max(min_val, default)

    def wanted_items(self):
        out = {}
        for name, entry in (self.cfg.get('buy_items') or {}).items():
            if isinstance(entry, dict) and entry.get('on'):
                q = str(entry.get('qty') or '').strip()
                out[name] = int(q) if q.isdecimal() and int(q) > 0 else None
        return out

    def pop_items(self):
        out = {}
        for biome, items in (self.cfg.get('pop_items') or {}).items():
            if not isinstance(items, dict):
                continue
            got = {}
            for n, a in items.items():
                s = str(a).strip()
                got[n] = int(s) if s.isdecimal() and int(s) > 0 else 1
            if got:
                out[biome] = got
        return out

    def sell_every(self):
        return self.cfg_int('fish_sell', 0, 0)

    def rune_delay(self):
        return self.cfg_int('rune_after', 0, 0)

    def sell_amount(self):
        return self.cfg_int('fish_sell_amount', 10, 1)

    def _correct_aura(self, quiet=False):
        typed = self.cfg_str('equip_aura').strip()
        if not typed:
            return None
        name = equip.resolve(typed)
        if name is None:
            return None
        if name != typed:
            self.cfg['equip_aura'] = name
            self.remember()
            if not quiet:
                note('equip', '"%s" read as %s' % (typed, name))
        return name

    def remember(self):
        try:
            with self._lock:
                self.wanted = self.wanted_items()
                self.pop_list = self.pop_items()
                save = {
                    'auto_items': self.cfg_bool('auto_items'),
                    'rune_on': self.cfg_bool('rune_on'),
                    'rune_biomes': list(self.cfg.get('rune_biomes') or list(RUNE_BIOMES)),
                    'rune_after': self.rune_delay(),
                    'selector_on': self.cfg_bool('selector_on'),
                    'selector_biome': self.cfg_str('selector_biome', 'HEAVEN'),
                    'pop_on': self.cfg_bool('pop_on'),
                    'pop_items': self.pop_list,
                    'anti_afk': self.cfg_bool('anti_afk', True),
                    'merchant_on': self.cfg_bool('merchant_on'),
                    'webhook_url': clean_url(self.cfg_str('webhook_url')),
                    'private_server': game.tidy_link(self.cfg_str('private_server')),
                    'auto_reconnect': self.cfg_bool('auto_reconnect'),
                    'rejoin_browser': self.cfg_bool('rejoin_browser'),
                    'low_end': self.cfg_bool('low_end'),
                    'eden_on': self.cfg_bool('eden_on'),
                    'eden_path': self.cfg_bool('eden_path', True),
                    'eden_record': self.cfg_bool('eden_record'),
                    'eden_ping': self.cfg_str('eden_ping').strip(),
                    'fish_on': self.cfg_bool('fish_on'),
                    'fish_vip': self.cfg_bool('fish_vip', True),
                    'fish_sell': self.sell_every(),
                    'fish_sell_all': self.cfg_bool('fish_sell_all', True),
                    'fish_full_check': self.cfg_bool('fish_full_check', True),
                    'fish_sell_amount': self.sell_amount(),
                    'collect_on': self.cfg_bool('collect_on'),
                    'collect_merchants': list(self.cfg.get('collect_merchants') or ['Jester', 'Mari', 'Rin']),
                    'clip_on': self.cfg_bool('clip_on'),
                    'clip_min': self.cfg_str('clip_min', '1,000,000,000').strip(),
                    'clip_quality': self.cfg_str('clip_quality', '768p'),
                    'clip_key_on': self.cfg_bool('clip_key_on'),
                    'clip_keys': self.cfg_str('clip_keys', 'Win+Alt+G'),
                    'equip_on': self.cfg_bool('equip_on'),
                    'equip_aura': self.cfg_str('equip_aura').strip(),
                    'roblox_username': self.cfg_str('roblox_username').strip(),
                    'roblox_uid': self.cfg_str('roblox_uid').strip(),
                    'tutorial_seen': self.cfg_bool('tutorial_seen'),
                    'buy_items': self.cfg.get('buy_items') or {},
                    'buy_list': '',
                }
                game.save_settings(save)
        except Exception as e:
            note('config', 'save failed: %s: %s' % (type(e).__name__, e))

    # --------------------------------------------------------------- Telemetry & UI State
    def _sync_live_roblox_log(self, initial=False):
        try:
            latest = game.newest_log()
            if not latest or not os.path.exists(latest):
                return False
            with open(latest, 'rb') as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 131072), os.SEEK_SET)
                tail = f.read().decode('utf-8', errors='replace')
            found_b, found_a = None, None
            for line in reversed(tail.splitlines()):
                if found_b is None:
                    b = game.biome_from_line(line)
                    if b:
                        found_b = b.upper()
                if found_a is None:
                    a = game.aura_from_line(line)
                    if a and a != '_None_':
                        found_a = a
                if found_b and found_a:
                    break
            changed = False
            if found_b and found_b != self.biome_now and (initial or not self.running):
                self.biome_now = found_b
                changed = True
            if found_a and found_a != self.aura_logged[0]:
                self.aura_logged = (found_a, time.time())
                changed = True
            return changed
        except Exception:
            return False

    def _poll_live_telemetry(self):
        while not self._closing:
            try:
                self._sync_live_roblox_log()
            except Exception:
                pass
            time.sleep(1.0)

    def build_state(self):
        with self._lock:
            if self.running and self.run_wall > 0:
                elapsed = max(0, int(time.time() - self.run_wall))
                h, rem = divmod(elapsed, 3600)
                m, s = divmod(rem, 60)
                uptime = '%02d:%02d:%02d' % (h, m, s)
            else:
                uptime = '00:00:00'

            r_up = game.find_roblox_window() is not None
            bnow = base_biome(self.biome_now or 'NORMAL') or 'NORMAL'
            r, g, b = biome_rgb(bnow)
            biomes_meta = {
                k: {
                    'pretty': pretty(k),
                    'rate': BIOME_RATES.get(k, 'Event Biome'),
                    'img': biome_web_path(k),
                }
                for k in BIOME_COLOURS
            }
            hist = [
                {
                    'biome': h_item['biome'],
                    'pretty': pretty(h_item['biome']),
                    'time': h_item['time'],
                    'rare': is_rare(h_item['biome']),
                    'img': biome_web_path(h_item['biome']),
                }
                for h_item in reversed(self._history[-25:])
            ]
            biome_counts = [
                {
                    'key': k,
                    'name': pretty(k),
                    'count': int(self._biome_counts.get(k, 0)),
                    'color': '#%06x' % biome_colour(k),
                    'rate': BIOME_RATES.get(k, 'Event Biome'),
                    'img': biome_web_path(k),
                    'rare': is_rare(k),
                }
                for k in COUNTS_ORDER
            ]
            biome_counts_total = int(sum(item['count'] for item in biome_counts))
            with _log_lock:
                logs = [{'ts': ts, 'tag': tag, 'msg': msg} for ts, tag, msg in _recent_logs[-100:]]

            return {
                'cfg': json.loads(json.dumps(self.cfg)),
                'running': self.running,
                'phase': self.phase_text,
                'uptime': uptime,
                'player_name': self.player_name,
                'roblox_uid': self.roblox_uid,
                'avatar_url': '/avatar.png',
                'roblox_up': r_up,
                'biome_now': bnow,
                'biome_pretty': pretty(bnow),
                'biome_rate': BIOME_RATES.get(bnow, 'Event Biome'),
                'biome_rgb': '%d, %d, %d' % (r, g, b),
                'biome_img': biome_web_path(bnow),
                'rares_count': self.rares_count,
                'biome_counts': biome_counts,
                'biome_counts_total': biome_counts_total,
                'aura_now': (self.aura_logged[0] if self.aura_logged[0] and self.aura_logged[0] != '_None_' else ''),
                'cache_bust': self.cache_bust,
                'drives': dict(selector.DRIVES),
                'potions': list(potions.POTIONS),
                'known_items': list(shop.KNOWN_ITEMS),
                'testers': list(TESTERS),
                'biomes': biomes_meta,
                'history': hist,
                'logs': logs,
            }

    # --------------------------------------------------------------- Plumbing / Notices
    def phase(self, text, colour=TEXT):
        clean = (text or '').replace(' -- ', ', ').replace(' - ', ', ')
        self.phase_text = clean or 'idle'
        if self._window is not None:
            try:
                title = TITLE if not clean or clean == 'idle' else '%s  |  %s' % (TITLE, clean)
                self._window.set_title(title)
            except Exception:
                pass

    def _set(self, **kw):
        if 'toast' in kw:
            self.notice(kw['toast'], BAD, 12000)
        if 'phase' in kw:
            self.phase(kw['phase'], kw.get('colour', TEXT))
        if 'biome' in kw:
            b_text, b_col = kw['biome']
            self.phase(b_text, b_col)
        if kw.get('key'):
            self._key_notice(kw)
        act = kw.get('action')
        if act == 'start' and self.running and game.ABORT:
            self.start_again = True
            self.phase('stopping - starting again after it', DIM)
        elif act == 'start' and not self.running:
            self.phase('starting', GOOD)
            self.start()
        elif act == 'stop' and self.running:
            self.stop()
        elif act == 'quit':
            self.close()
        elif act == 'idle':
            self.phase('idle', DIM)
            if self._key_stop:
                self._key_stop = False
                self.notice('MMacro: stopped', DIM)
            if self.start_again:
                self.start_again = False
                threading.Timer(0.2, self.start).start()

    def notice(self, text, colour=TEXT, ms=2200):
        try:
            self._toast.show(text, colour, ms)
        except Exception as e:
            note('ui', 'notice: %s: %s' % (type(e).__name__, e))

    def _key_notice(self, kw):
        if kw.get('action') == 'start':
            if self.running and game.ABORT:
                self.notice('MMacro: stopping - starts again right after', DIM)
            elif self.running:
                self.notice('MMacro is already running  (F2 stops it)', ACCENT)
            else:
                self.notice('MMacro: starting', GOOD, 1200)
        elif kw.get('action') == 'stop':
            self._key_stop = self.running
            self.notice('MMacro: stopping' if self.running else 'MMacro is not running  (F1 starts it)',
                        BAD if self.running else DIM)

    def _poll_hotkeys(self):
        state, was = ctypes.windll.user32.GetAsyncKeyState, {}
        while not self._closing:
            for vk, key in ((0x70, keyboard.Key.f1), (0x71, keyboard.Key.f2)):
                held = bool(state(vk) & 0x8000)
                if held and not was.get(vk) and not self._capturing:
                    self.on_key(key)
                was[vk] = held
            time.sleep(0.01)

    def on_key(self, key, *_):
        try:
            kb = self._keyboard
            if key is not kb.Key.f1 and key is not kb.Key.f2:
                return True
            now = time.perf_counter()
            which = 'start' if key is kb.Key.f1 else 'stop'
            if now - self._last_hotkey.get(which, 0.0) < 0.75:
                return True
            self._last_hotkey[which] = now
            note('run', 'F%d pressed' % (1 if which == 'start' else 2))
            if which == 'stop':
                game.ABORT = True
            self._set(action=which, key=True)
        except Exception:
            pass
        return True

    # --------------------------------------------------------------- Biome & Merchant watchers
    def start_biomes(self, url):
        if self.biome_stop is not None and not self.biome_stop.is_set():
            return
        if not (url.startswith('https://') or self.merchant_detect or self.clipper or self.equip_aura or self.rune_biomes
                or self.selector_biome or self.pop_biomes):
            return
        self.biome_stop = threading.Event()
        threading.Thread(target=self._watch_biomes, args=(url,), daemon=True).start()

    def _watch_biomes(self, url):
        cfg = game.load_settings()
        stop = self.biome_stop
        failed = None
        post_event(url, 'Macro started', '', EMBED_GOOD)
        self._set(biome=('watching', GOOD))
        try:
            watcher = BiomeWatcher(float(cfg.get('cooldown_seconds') or 300))
            self._merchant_posted = {}
            last_aura = None
            for line in game.follow(stop.is_set):
                try:
                    last_aura = self._read_line(line, url, watcher, last_aura)
                except Exception as e:
                    note('biomes', 'a log line was not read: %s: %s' % (type(e).__name__, e))
        except Exception as e:
            failed = '%s: %s' % (type(e).__name__, e)
        finally:
            if failed:
                post_event(url, 'Biome detection stopped', '`%s`' % failed, EMBED_BAD, 'Biome')
            else:
                post_event(url, 'Macro stopped')
            if self.biome_stop is stop:
                self.biome_stop = None
            self._set(biome=(failed, BAD) if failed else ('idle', DIM))

    def merchant_arrived(self, merchant, how, url=None):
        posted = self._merchant_posted
        if time.time() - posted.get(merchant, 0.0) <= MERCHANT_REPEAT_S:
            return
        need = BOSS_BIOMES.get(merchant)
        if need and self.biome_now and not rune_biome(self.biome_now, {need}):
            if time.monotonic() - self._boss_seen.get(merchant, -1e9) > BOSS_EARLY_S:
                note('merchant', '%s seen outside %s: not posted unless %s starts' % (merchant, pretty(need), pretty(need)))
            self._boss_seen[merchant] = time.monotonic()
            return
        posted[merchant] = time.time()
        note('merchant', '%s arrived (%s)' % (merchant, how))
        post_merchant(url or self.url, merchant, self.server_link or game.load_settings().get('private_server', ''))
        self._set(phase='%s arrived' % merchant, colour=GOOD)
        if self.collect and merchant in self.collect_names:
            self.merchant_due, self.merchant_at, self.merchant_tries = merchant, time.monotonic(), 0

    def _watch_cache(self):
        said = posted = False
        while not self._closing:
            try:
                came = self.cache.poll()
                said = posted = False
                if came and self.running and self.merchant_detect:
                    for name in came:
                        self.merchant_arrived(name, 'seen in Roblox\'s cache')
                self._keep_block()
            except Exception as e:
                if not said:
                    path = self.cache.cache() or ''
                    bad = merchant_cache.unreadable(path) if path else []
                    note('merchant', 'Roblox\'s cache could not be read: %s: %s (%s%s)' % (
                        type(e).__name__, e, path.replace(merchant_cache.LOCAL, '%LOCALAPPDATA%'),
                        '; cannot open ' + ', '.join(bad) if bad else ''))
                    said = True
                if not posted and self.running and self.merchant_detect:
                    post_event(self.url, 'Merchant detection is not working', CACHE_UNREADABLE, EMBED_BAD, 'Merchant')
                    posted = True
            time.sleep(2)

    def _keep_block(self):
        keys = {k for ks in merchant_cache.FILES.values() for k in ks}
        with self.block_lock:
            if self._closing or not keys:
                return
            if self.block_on:
                path = self.cache.cache()
                if not path:
                    return
                wrote = merchant_cache.block(keys, path)
                if wrote:
                    self.cache.forget(wrote)
                    past = self.loaded_already(wrote)
                    note('merchant', '%s %d merchant animation(s) in Roblox\'s cache%s' % (
                        'blocked again' if self.blocked else 'blocked', len(wrote),
                        ': this Roblox already loaded a real one' if past else ''))
                    self.got_past_block = self.got_past_block or past
                    self.blocked = {**self.blocked, **wrote}
                    self.block_path = path
            elif self.blocked or self.cache.ours:
                self._unblock(keys)

    def _unblock(self, keys):
        path = self.block_path or self.cache.cache()
        note('merchant', 'block taken out of Roblox\'s cache (%d)' % merchant_cache.unblock(keys, path))
        self.blocked, self.block_path = {}, None

    def loaded_already(self, blocked=None):
        blocked = self.blocked if blocked is None else blocked
        starts = []
        for p in game.roblox_processes():
            try:
                if p.name().lower() == 'robloxplayerbeta.exe':
                    starts.append(p.create_time())
            except Exception:
                pass
        return bool(starts) and any(t and t / 1000.0 > min(starts) for t in blocked.values())

    def _read_line(self, line, url, watcher, last_aura):
        biome = game.biome_from_line(line) if line else None
        self.biome_now = biome.upper() if biome else self.biome_now
        aura = game.aura_from_line(line) if line and (self.clipper or self.equip_aura) else None
        if aura == '_None_' and (last_aura is None or time.monotonic() - self.joined_at < JOIN_NONE_S):
            aura = None
        if aura:
            self.aura_logged = (aura, time.time())
        if aura and aura != last_aura:
            ours = (self.equip_aura and clipper.norm(aura) == clipper.norm(self.equip_aura)
                    and time.monotonic() - self.equip_busy_at < 120)
            if self.clipper and last_aura is not None and aura != '_None_' and not ours:
                self.clip_aura(aura, line)
            if self.equip_aura and clipper.norm(aura) != clipper.norm(self.equip_aura):
                note('equip', 'Roblox\'s log says %s is equipped now: %s goes back on'
                     % (aura, self.equip_aura))
                if self.equip_due is None:
                    self.equip_due = max(time.monotonic(), self.equip_busy_at + EQUIP_GAP_S)
            last_aura = aura
        change = watcher.feed(biome)
        if change:
            name, alert = change
            if alert:
                self.rares_count += 1
            self.rune_biome_changed(name)
            self.pop_biome_changed(name)
            for boss, at in list(self._boss_seen.items()):
                if time.monotonic() - at <= BOSS_EARLY_S and rune_biome(name, {BOSS_BIOMES[boss]}):
                    self.merchant_arrived(boss, 'seen just before %s started' % pretty(name))
            self._boss_seen.clear()
            append_history(name)
            with self._lock:
                self._biome_counts[base_biome(name) or name] += 1
                self._history.append({'biome': name, 'time': time.strftime('%H:%M:%S')})
                if len(self._history) > 100:
                    del self._history[:50]
            server = self.server_link or game.load_settings().get('private_server', '')
            times = (time.time() - self.run_wall, time.monotonic() - self.joined_at) if self.running else (None, None)
            post_biome(url, name, ping=alert, server=server, running=times[0], here=times[1])
            self._set(biome=(pretty(name), ACCENT if alert else DIM))
        return last_aura

    def clip_aura(self, aura, line):
        n = clipper.rarity(aura, self.biome_now, line)
        if n is not None and n < self.clip_min:
            return
        odds = '1 in {:,}'.format(n) if n else 'rarity unknown'
        note('clip', '%s rolled (%s) - saving a clip' % (aura, odds))
        self._set(phase='%s rolled - clipping' % aura, colour=GOOD)

        colour = next((c for least, c in CLIP_COLOURS if (n or 0) >= least), EMBED_INFO)
        shot = self.clipper.shot(time.time())

        def done(path):
            if path:
                how = 'Clipped using hotkey' if path is True else 'clips\\%s' % os.path.basename(path)
                post_event(self.url, 'Aura Clipped - %s' % aura, '', colour, 'Clip',
                           [('Rarity', odds, True), ('Biome', pretty(self.biome_now) or '-', True), ('Clip', how, True)],
                           shot=shot, thumb=biome_png(self.biome_now))
        self.clipper.clip('%s' % aura, done)

    # --------------------------------------------------------------- Actions
    def start(self):
        if self.running:
            return None
        self.server_link = game.tidy_link(self.cfg_str('private_server'))
        self.cfg['private_server'] = self.server_link
        self.reconnect_on = self.cfg_bool('auto_reconnect')
        self.played = False
        self.item_due = {}
        self.browser_rejoin = self.cfg_bool('rejoin_browser')
        self.slow_pc = self.cfg_bool('low_end')
        if self.reconnect_on and not game.deeplink(self.server_link):
            self.phase('auto reconnect needs a private server link', BAD)
            msg = 'Auto reconnect is on - paste a Roblox private server link on the Settings tab.'
            self.notice('Cannot start: ' + msg, BAD, 8000)
            return msg
        if game.roblox_elevated():
            self.phase('Roblox is running as administrator', BAD)
            msg = 'Roblox is running as administrator, so Windows will not let the macro click in it. Reopen Roblox normally.'
            self.notice('Cannot start: ' + msg, BAD, 8000)
            return msg
        self.merchant_detect = self.cfg_bool('merchant_on')
        if self.merchant_detect and not merchant_cache.cache_found():
            self.phase("Roblox's cache was not found", BAD)
            self.notice('Cannot start: ' + STORE_ROBLOX.split('\n')[0], BAD, 8000)
            return STORE_ROBLOX.split('\n')[0]
        self.collect = self.cfg_bool('collect_on')
        if self.collect and not self.merchant_detect:
            self.phase('auto merchant collection needs merchant detection', BAD)
            msg = 'Auto merchant collection needs Merchant Detection enabled.'
            self.notice('Cannot start: ' + msg, BAD, 8000)
            return msg

        self.wanted = self.wanted_items()
        self.collect_names = set(self.cfg.get('collect_merchants') or ['Jester', 'Mari', 'Rin'])
        self.merchant_due = None
        self.remember()
        self.url = clean_url(self.cfg_str('webhook_url'))
        self.use_items = self.cfg_bool('auto_items')
        self.rune_biomes = set(self.cfg.get('rune_biomes') or RUNE_BIOMES) if self.cfg_bool('rune_on') else set()
        self.rune_wait, self.rune_due = self.rune_delay(), None
        self.selector_biome = self.cfg_str('selector_biome', 'HEAVEN') if self.cfg_bool('selector_on') else None
        self.selector_due = time.monotonic() if self.selector_biome else None
        self.selector_refused = self.selector_missed = 0
        self.pop_list, self.pop_due, self.pop_left = self.pop_items(), None, None
        self.pop_biomes = set(self.pop_list) if self.cfg_bool('pop_on') else set()
        self.clip_min = clip_floor(self.cfg_str('clip_min', '1,000,000,000'))
        self.clipper = None
        if self.cfg_bool('clip_on') and self.cfg_bool('clip_key_on'):
            try:
                self.clipper = clipper.KeyClipper(self.cfg_str('clip_keys', 'Win+Alt+G'), lambda text: note('clip', text))
            except ValueError as e:
                note('clip', 'the clip key cannot be pressed (%s): no clips this run' % e)
        elif self.cfg_bool('clip_on'):
            self.clipper = clipper.Clipper(lambda text: note('clip', text),
                                           height=clipper.HEIGHTS.get(self.cfg_str('clip_quality', '768p'), clipper.HEIGHT))
        if self.clipper:
            self.clipper.start()
        self.equip_aura = self._correct_aura() if self.cfg_bool('equip_on') else None
        if self.cfg_bool('equip_on') and not self.equip_aura:
            note('equip', 'no aura in the list to keep equipped: Keep an aura equipped is off this run')
        self.equip_due = time.monotonic() if self.equip_aura else None
        self.crack_on, self.in_dimension = self.cfg_bool('eden_on'), True
        self.run_wall, self.equip_busy_at, self.equip_fails = time.time(), -EQUIP_GAP_S, 0
        self.start_biomes(self.url)
        self.running = True
        self.phase('running', GOOD)
        threading.Thread(target=self._guard, daemon=True).start()
        return None

    def tell(self, title, detail='', colour=None, area='Macro'):
        thumb = biome_png(self.biome_now) if area in ('Biome', 'Pop', 'Rune', 'Selector') and self.biome_now else None
        post_event(self.url, title, detail, colour if colour is not None else EMBED_INFO, area, thumb=thumb)
        self._set(phase='%s%s' % (title, ' - ' + detail if detail else ''))

    def _guard(self):
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000003)
        try:
            for k in itertools.count():
                try:
                    self.play()
                    if not self.restart_run:
                        return
                except Exception as e:
                    try:
                        game.release_all()
                    except Exception:
                        pass
                    why = '%s: %s' % (type(e).__name__, e)
                    note('crash', '%s\n%s' % (why, traceback.format_exc()[-1500:]))
                    if game.ABORT and not self.restart_run:
                        self.tell('Macro crashed', '`%s`' % why, EMBED_BAD)
                        return
                    if not self.restart_run:
                        wait = CRASH_WAITS[min(k, len(CRASH_WAITS) - 1)]
                        self.tell('Macro crashed', '`%s`\nStarting again in %ds' % (why, wait), EMBED_BAD)
                        if not self.nap(wait):
                            return
                if self.restart_run:
                    self.restart_run = False
                    try:
                        game.release_all()
                    except Exception:
                        pass
                    note('run', 'run restarted after a stall')
        finally:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            self.running = False
            if self.biome_stop is not None:
                self.biome_stop.set()
            if self.clipper is not None:
                self.clipper.stop()
            self._set(action='idle')

    def nap(self, seconds, halt=None):
        halt = halt or (lambda: game.ABORT)
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            self.beat = time.monotonic()
            if halt():
                return False
            time.sleep(0.2)
        return not halt()

    def play(self):
        game.ABORT = False
        game.arm()
        game.fresh_session()
        game.set_pace(2.0 if self.slow_pc else 1.0)
        note('run', 'started: %s' % device_line())
        self.joined_at = time.monotonic()
        self.need_rejoin = self.out_since = None
        self.watch = game.Watch()
        self.watch.poll()
        if not game.roblox_running():
            self.need_rejoin = 'Roblox is not running'
        elif self.merchant_detect and self.reconnect_on and self.loaded_already():
            note('merchant', 'this Roblox loaded a merchant before the block: reopening it so every visit shows')
            game.close_roblox()
            self.need_rejoin = 'a merchant was loaded before the block'
        self.got_past_block = False
        self.run_id += 1
        self.beat = time.monotonic()
        threading.Thread(target=self._watch_connection, args=(self.run_id,), daemon=True).start()
        if not self.ready_to_play():
            game.release_all()
            return
        self.fit_roblox()
        if self.need_rejoin is None:
            self.daily_later()

        seer = eden.Watcher() if self.cfg_bool('eden_on') else None
        afk_due = time.monotonic() + AFK_EVERY_S
        stray_due = time.monotonic() + STRAY_EVERY_S
        self.daily_at = next_daily()
        halt = lambda: game.ABORT or self.need_rejoin is not None
        busy = lambda: halt() or self.merchant_due is not None or self.pop_due is not None
        self.fisher = fishing.Fisher(
            vip=self.cfg_bool('fish_vip', True),
            sell_every=self.sell_every(),
            sell_amount=self.sell_amount(),
            sell_all=self.cfg_bool('fish_sell_all', True),
            full_check=self.cfg_bool('fish_full_check', True),
            say=lambda m: (note('fishing', m), self._ai_observe_msg(m)),
            report=self.post_fishing
        ) if self.cfg_bool('fish_on') else None
        self.check_chat_on_start()
        self.ai_preflight()
        self._set(phase='running', colour=GOOD)
        while not game.ABORT:
            if self.need_rejoin:
                self.merchant_due = None
                self._merchant_posted = {}
                if self.fisher:
                    self.fisher.hold = self.fisher.pause = False
                if not self.reconnect():
                    note('run', 'stopped: could not get back in')
                    self.tell('Could not get back in', 'Macro stopped', EMBED_BAD, 'Connection')
                    break
                self.joined_at = time.monotonic()
                self.got_past_block = False
                self.in_dimension = False
                self.fit_roblox()
                self.check_chat_on_start()
                if self.fisher:
                    self.fisher.lost()
                if self.crack_on and not self.need_rejoin:
                    self.use_crack(halt, 'back to Eden\'s dimension after the rejoin')
            if (self.got_past_block and self.merchant_detect and self.reconnect_on and not self.merchant_due
                    and not (self.fisher and self.fisher.line_out) and not is_rare(self.biome_now)):
                self.got_past_block = False
                note('merchant', 'Roblox loaded a merchant\'s real animation and keeps it: reopening it so every '
                                 'visit shows again')
                game.close_roblox()
                self.need_rejoin = 'a merchant was loaded past the block'
                continue
            self.check_in_game()
            if self.need_rejoin:
                continue
            if time.monotonic() >= stray_due and not busy():
                stray_due = time.monotonic() + STRAY_EVERY_S
                self.close_strays()
            if self.pop_due and not self.need_rejoin:
                if self.fisher:
                    self.drop_fishing(halt, '%s started: stopping to pop' % pretty(self.pop_due))
                self.pop_turn(halt)
                if self.fisher:
                    self.fisher.lost()
                continue
            if self.merchant_due and time.monotonic() - self.merchant_at > MERCHANT_STALE_S:
                note('merchant', '%s came %d s ago: gone by now, not teleporting' % (self.merchant_due, MERCHANT_STALE_S))
                self.merchant_due = None
            if self.merchant_due and not self.need_rejoin:
                if self.fisher:
                    self.drop_fishing(halt, '%s arrived: stopping to go buy' % self.merchant_due)
                self.merchant_tries = getattr(self, 'merchant_tries', 0) + 1
                if self.collect_merchant(self.merchant_due, halt) is not False or self.merchant_tries >= MERCHANT_TRIES:
                    self.merchant_due, self.merchant_tries = None, 0
                if self.fisher:
                    self.fisher.lost()
                continue
            if self.use_items and not game.ABORT and self.items_due():
                self.items_turn(busy)
            if (self.rune_due is not None and time.monotonic() >= self.rune_due and not busy()):
                self.between_fish(busy, 'rune', 'Cursed Rune Fragment due', self.rune_turn)
            if (self.selector_due is not None and time.monotonic() >= self.selector_due and not busy()
                    and not rune_biome(self.biome_now, HOLD_BIOMES)
                    and not self.selector_landed()):
                self.between_fish(busy, 'selector', 'Biome Selector due', self.selector_turn)
            if time.time() >= self.daily_at and not busy():
                self.between_fish(busy, 'daily', 'daily rewards reset', self.daily_reset_turn)
            if game.after_align and time.monotonic() >= self.daily_by and not busy():
                game.after_align = None
                self.claim_daily()
            if (self.equip_due is not None and time.monotonic() >= self.equip_due and not busy()):
                self.between_fish(busy, 'equip', 'putting %s back on' % self.equip_aura, self.equip_turn)
            if seer is not None and not self.need_rejoin and seer.seen():
                self.eden_found()
                afk_due = time.monotonic() + EDEN_AFK_REST_S
                self.nap(eden.COOLDOWN_S, busy)
                if self.fisher:
                    self.fisher.lost()
            if self.fisher is not None and not busy():
                if self.fisher.pause and not self.fisher.line_out:
                    self.fisher.pause, self.fisher.recast = False, self.fisher.at_spot
                step_ok = False
                try:
                    step_ok = bool(self.fisher.step(busy, LOOK_EVERY_S * 4))
                except Exception as e:
                    note('fishing', 'failed - %s: %s' % (type(e).__name__, e))
                    self.ai_record_issue('sell', '%s: %s' % (type(e).__name__, e))
                    self.ai_heal_screen('sell')
                    self.fisher.lost()
                if self.fisher.rejoin and not is_rare(self.biome_now):
                    why, self.fisher.rejoin = self.fisher.rejoin, False
                    if 'Collection' in (why or ''):
                        self.ai_record_issue('collection', why)
                        self.ai_heal_screen('collection')
                    if self.reconnect_on:
                        game.close_roblox()
                        self.need_rejoin = why
                    else:
                        note('fishing', 'not rejoining: Auto reconnect is off')
                self.beat = time.monotonic()
                if not step_ok and not busy():
                    self.ai_heal_screen('fishing')
                    self.nap(LOOK_EVERY_S)
                continue
            if self.cfg_bool('anti_afk', True) and time.monotonic() >= afk_due and not self.need_rejoin:
                self.jump()
                afk_due = time.monotonic() + AFK_EVERY_S
            self.nap(LOOK_EVERY_S)

        game.release_all()
        if self.restart_run:
            note('run', 'run ended by the stall watchdog')
            return
        note('run', 'run ended%s' % (' (Stop pressed)' if game.ABORT else ''))

    def jump(self):
        try:
            if game.take_foreground(tries=2) is not None:
                note('run', 'anti-AFK: two jumps')
                game.tap(' ', gap=0.2)
                game.tap(' ')
        except Exception as e:
            note('run', 'anti-AFK skipped: %s: %s' % (type(e).__name__, e))

    def eden_found(self):
        halt = lambda: game.ABORT or self.need_rejoin is not None
        ping = self.cfg_str('eden_ping')
        note('eden', 'Eden on screen')
        self._set(phase='Eden on screen', colour=GOOD)
        game.take_foreground(tries=2)
        if self.cfg_bool('eden_record'):
            threading.Thread(target=eden.record, args=(eden.RECORD_S, halt), daemon=True).start()
        post_shot(self.url, 'Eden Detected', EMBED_GOOD, ping, area='Eden')
        if not self.nap(eden.SETTLE_S, halt):
            return
        path, began, go = self.cfg_bool('eden_path', True), time.monotonic(), 0
        while not halt():
            go += 1
            tried = time.monotonic()
            if self.eden_try(path, go, halt):
                note('eden', 'contract signed (go %d)' % go)
                post_shot(self.url, 'Eden Obtained', EMBED_GOLD, ping, area='Eden')
                return
            if halt():
                return
            if path and time.monotonic() - began >= EDEN_GIVE_UP_S:
                note('eden', 'no contract in %d minutes: giving up' % (EDEN_GIVE_UP_S // 60))
                self.tell('Eden Contract not seen', 'Tried for %d minutes, giving up' % (EDEN_GIVE_UP_S // 60), EMBED_BAD,
                          'Eden')
                return
            note('eden', 'the contract never showed (go %d): trying again' % go)
            if go == 1:
                self.tell('Eden Contract not seen', 'Trying again every %ds' % EDEN_RETRY_S, EMBED_BAD, 'Eden')
            if not self.nap(max(0.0, EDEN_RETRY_S - (time.monotonic() - tried)), halt):
                return

    def eden_try(self, path, go, halt):
        try:
            if path:
                if go > 1:
                    if not fishing.respawn(halt):
                        return False
                    self.in_dimension = False
                if not self.in_dimension and not self.use_crack(halt, 'the Eden walk starts at its spawn (go %d)' % go):
                    return False
                if not game.align_camera(halt):
                    note('eden', 'Collection did not square the camera up: not walking')
                    return False
                eden.tilt()
                note('eden', 'walking the path (go %d)' % go)
                eden.walk(halt)
                time.sleep(0.5)
            if halt():
                return False
            game.down('e')
            time.sleep(0.1)
            game.up('e')
        except game.NotFocused as e:
            note('eden', 'not this go: %s' % e)
            return False
        if not self.nap(eden.TALK_S, halt):
            return False
        if not game.press_point('contract', settle=0.2):
            note('eden', 'the Contract button was not pressed: press Set Contract on the Eden tab')
            return False
        return eden.signed(halt)

    def _watch_connection(self, run_id=0):
        last = time.time()
        while self.running and not self._closing and run_id == self.run_id:
            gap, last = time.time() - last, time.time()
            if gap > SLEPT_S:
                self.beat = time.monotonic()
                note('run', 'the PC was asleep for %d minutes: nothing ran' % round(gap / 60))
                self.tell('PC was asleep', 'Nothing ran for %d minutes. MMacro keeps the PC awake, but not through a '
                          'closed lid, Sleep or a flat battery' % round(gap / 60), EMBED_BAD)
            watch = self.watch
            if watch is not None and not self.rejoining and self.need_rejoin is None:
                try:
                    why = watch.trouble()
                except Exception:
                    why = None
                if why:
                    self.need_rejoin = why
                    try:
                        game.release_all()
                    except Exception:
                        pass
            if time.monotonic() - self.beat > STALL_S and not self.restart_run and not game.ABORT:
                note('run', 'the run has not moved for %d minutes: restarting it' % (STALL_S // 60))
                self.tell('Macro stuck', 'No progress for %d minutes, restarting the run' % (STALL_S // 60), EMBED_BAD)
                self.restart_run = True
                game.ABORT = True
            time.sleep(WATCH_EVERY)

    def connected(self, watch=None):
        watch = watch or game.Watch()
        watch.poll()
        return game.roblox_running() and watch.state == 'joined' and game.in_game(watch)

    def ready_to_play(self):
        watch = self.watch or game.Watch()
        why = watch.trouble(quiet_s=float('inf'))
        if why and game.roblox_running() and game.find_play() is None:
            note('run', 'the log says "%s", but the client is in a game: starting anyway' % why)
            why = watch.state = watch.dropped = None
        if why:
            self.need_rejoin = why
            if not self.reconnect():
                self.tell('Roblox is not ready', capital(why), EMBED_BAD, 'Connection')
                return False
            self.joined_at = time.monotonic()
        return True

    def fit_roblox(self):
        try:
            def say(m):
                note('window', m)
                if 'F11' in m:
                    self._set(toast=m)
            game.fit_window(say=say)
        except Exception as e:
            note('window', 'sizing the Roblox window failed: %s: %s' % (type(e).__name__, e))

    def check_chat_on_start(self):
        """Detect whether Roblox chat is ON when starting/rejoining and turn it off if open."""
        try:
            if game.roblox_window() is None:
                return None
            if game.chat_open():
                note('chat', 'chat is ON at start: turning it off')
                ok = game.close_chat()
                note('chat', 'chat turned OFF' if ok else 'chat still appeared open after clicking toggle')
                return False
            note('chat', 'chat is OFF')
            return True
        except Exception as e:
            note('chat', 'chat check failed: %s: %s' % (type(e).__name__, e))
            return None

    def _ai_memory_path(self):
        return os.path.join(game.APP_DIR, 'ai_memory.json')

    def _load_ai_memory(self):
        try:
            with open(self._ai_memory_path(), encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_ai_memory(self, data):
        try:
            os.makedirs(game.APP_DIR, exist_ok=True)
            with open(self._ai_memory_path(), 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def _scan_previous_run_logs(self):
        """Read the previous run slice in logs.txt and classify issues it hit."""
        path = os.path.join(game.APP_DIR, 'logs.txt')
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                lines = f.readlines()[-250:]
        except OSError:
            return set()
        starts = [i for i, ln in enumerate(lines) if '[run] started:' in ln]
        if len(starts) >= 2:
            prev = lines[starts[-2]:starts[-1]]
        elif len(starts) == 1:
            prev = lines[:starts[0]]
        else:
            prev = lines
        issues = set()
        for ln in prev:
            if 'Collection would not open' in ln or 'Collection did not open' in ln or 'Collection would not shut' in ln:
                issues.add('collection')
            if 'Sell Alls went unsold' in ln or 'sale did not go through' in ln or '[fishing] failed' in ln:
                issues.add('sell')
            if 'No bite in 30 s' in ln or 'still no bite' in ln or "Flarg's message never came up" in ln:
                issues.add('route')
            if 'NotFocused' in ln or 'would not come forward' in ln:
                issues.add('focus')
            if 'chat is ON' in ln or 'chat is open' in ln:
                issues.add('chat')
        return issues

    def ai_record_issue(self, kind, detail=''):
        """Persist a runtime failure lesson so the next run auto-corrects for it."""
        mem = self._load_ai_memory()
        counts = dict(mem.get('counts') or {})
        counts[kind] = int(counts.get(kind, 0)) + 1
        mem['counts'] = counts
        mem['pending'] = sorted(set(mem.get('pending') or []) | {kind})
        mem['last_detail'] = (detail or '')[:160]
        mem['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        self._save_ai_memory(mem)

    def _ai_observe_msg(self, msg):
        m = msg or ''
        if 'Collection would not open' in m or 'Collection would not shut' in m:
            self.ai_record_issue('collection', m)
        elif 'Sell Alls went unsold' in m or 'sale did not go through' in m:
            self.ai_record_issue('sell', m)
        elif 'still no bite' in m or "Flarg's message never came up" in m:
            self.ai_record_issue('route', m)
        elif 'fish ' in m and 'caught' in m:
            # Successful catches decay pending warnings once the correction worked
            mem = self._load_ai_memory()
            if mem.get('pending'):
                mem['pending'] = []
                self._save_ai_memory(mem)

    def ai_heal_screen(self, reason=''):
        """Clear stuck chat, menus, shop, dialogue, and keys before resuming."""
        try:
            game.release_all()
        except Exception:
            pass
        if game.roblox_window() is None:
            return
        try:
            if game.chat_open():
                note('ai', 'auto-correct (%s): closing open chat' % (reason or 'recover'))
                game.close_chat()
            if game.collection_open() is True:
                note('ai', 'auto-correct (%s): closing stuck Collection' % (reason or 'recover'))
                game.press_point('exit_collection', settle=0.4)
            if any(k in (reason or '').lower() for k in ('shop', 'sell', 'fishing', 'collection')):
                points.click('fishingShopCloseButton', 0.2)
            points.leave_dialogue(skip=True)
            self.close_guis()
        except Exception as e:
            note('ai', 'screen cleanup note: %s: %s' % (type(e).__name__, e))

    def ai_preflight(self):
        """Check mistakes from the previous run and apply automatic fixes before starting."""
        mem = self._load_ai_memory()
        issues = set(mem.get('pending') or []) | self._scan_previous_run_logs()
        if not issues:
            note('ai', 'previous run finished cleanly (no errors to correct)')
            game.COLLECTION_EXTRA_S = 0.0
            return
        actions = []
        if 'collection' in issues:
            game.COLLECTION_EXTRA_S = 0.3
            actions.append('added +0.3s Collection hover/exit settle')
        else:
            game.COLLECTION_EXTRA_S = 0.0
        if 'sell' in issues:
            fishing.slow = min(fishing.SLOW_MAX, max(fishing.slow, 0.15))
            actions.append('set Sell All guard delay +%.2fs' % fishing.slow)
        if 'focus' in issues:
            game.take_foreground(tries=3)
            actions.append('re-focused Roblox')
        if issues & {'collection', 'sell', 'route', 'chat'}:
            self.ai_heal_screen('last run had: ' + ', '.join(sorted(issues)))
            actions.append('cleared chat/shop/menus')
        note('ai', 'auto-corrected from last run (%s): %s' % (', '.join(sorted(issues)), '; '.join(actions)))
        mem['last_applied'] = sorted(issues)
        mem['pending'] = []
        self._save_ai_memory(mem)

    def reconnect(self):
        self.rejoining = True
        try:
            back = self._reconnect()
        finally:
            self.rejoining = False
        return back

    def _reconnect(self):
        why, self.need_rejoin = self.need_rejoin, None
        self.out_since = None
        if 'by itself' in (why or '') and self.connected():
            note('connection', 'already back in the game (%s)' % why)
            self.daily_later()
            self.watch = game.Watch()
            return True
        if not self.reconnect_on:
            return self.wait_for_game(why or '')
        note('connection', 'reconnecting: %s' % (why or ''))
        self.tell('Reconnecting', capital(why), EMBED_BAD, 'Connection')
        k = -1
        while True:
            k += 1
            self.beat = time.monotonic()
            if game.ABORT:
                return False
            failed = ''
            try:
                ok = game.rejoin(self.server_link, stop=lambda: game.ABORT, browser=self.browser_rejoin,
                                 frozen=k > 0 or (why or '').startswith(game.FROZEN),
                                 say=lambda m: (note('connection', m), self._set(phase='reconnecting - %s' % m, colour=DIM)))
                self.beat = time.monotonic()
                if ok and not self.wait_in_game():
                    ok, failed = False, 'not in the game %d s after joining' % IN_GAME_S
            except Exception as e:
                ok, failed = False, '%s: %s' % (type(e).__name__, e)
            finally:
                self.watch = game.Watch()
            if game.ABORT:
                return False
            if ok:
                note('connection', 'rejoined')
                self.tell('Rejoined the private server', '', EMBED_GOOD, 'Connection')
                self.daily_later()
                return True
            wait = REJOIN_WAITS[min(k, len(REJOIN_WAITS) - 1)]
            note('connection', 'rejoin %d failed (%s), again in %d s' % (k + 1, failed or 'see above', wait))
            self.tell('Could not rejoin', '%sTrying again in %ds' % (capital(failed) + '\n' if failed else '', wait),
                      EMBED_BAD, 'Connection')
            if not self.nap(wait):
                return False

    def wait_for_game(self, why):
        note('connection', 'auto reconnect is off: waiting for the game to be back (%s)' % why)
        self.tell('Disconnected', 'Auto Reconnect is disabled', EMBED_BAD, 'Connection')
        clicked, watch = 0.0, game.Watch()
        while self.nap(5):
            if not game.roblox_running():
                continue
            if self.connected(watch):
                note('connection', 'back in the game')
                self.tell('Back in the game', '', EMBED_GOOD, 'Connection')
                self.daily_later()
                self.watch = game.Watch()
                return True
            if game.find_play() is not None and time.monotonic() - clicked > PLAY_EVERY_S:
                self.press_play()
                clicked = time.monotonic()
        return False

    def wait_in_game(self, limit=IN_GAME_S):
        end, clicked, clear_since = time.monotonic() + limit, 0.0, None
        watch = game.Watch()
        while time.monotonic() < end and not game.ABORT:
            if not game.roblox_running():
                return False
            watch.poll()
            if watch.state == 'joined' and game.in_game(watch):
                return True
            if game.find_play() is not None or (watch.in_menu and time.time() - watch.menu_at < game.MENU_S):
                clear_since = None
                if time.monotonic() - clicked > PLAY_EVERY_S:
                    self.press_play()
                    clicked = time.monotonic()
            elif watch.path is None or watch.state == 'joined':
                clear_since = clear_since or time.monotonic()
                if time.monotonic() - clear_since > 20:
                    return True
            time.sleep(2)
        return False

    def press_play(self):
        try:
            at = game.find_play()
            if at is not None:
                game.click(*at)
            elif not game.press_point('play', settle=1.0):
                return
            note('connection', 'pressed Play (%s)' % ('seen' if at else 'Set Play' if 'play' in game.load_points()
                                                       else 'built-in spot'))
        except Exception as e:
            note('connection', 'pressing Play failed: %s: %s' % (type(e).__name__, e))

    def check_in_game(self):
        now, mono = time.time(), time.monotonic()
        if mono < self._look_at or self.need_rejoin:
            return
        self._look_at = mono + 5
        watch = self.watch
        logged_in = watch is not None and watch.path is not None and game.in_game(watch)
        menu = watch is not None and watch.in_menu and now - watch.menu_at < game.MENU_S
        out = game.roblox_running() and not logged_in and (menu or game.find_play() is not None)
        if not out:
            self.out_since = None
            if self.played and logged_in:
                self.played = False
                self.daily_later()
            return
        self.out_since = self.out_since or mono
        if mono - self._played > PLAY_EVERY_S:
            self.press_play()
            self._played = mono
            self.played = True
        if mono - self.out_since > OUT_S:
            note('connection', 'not in a game for %d minutes' % (OUT_S // 60))
            self.out_since = None
            self.need_rejoin = 'not in a game for %d minutes' % (OUT_S // 60)

    def daily_reset_turn(self):
        self.daily_at = next_daily()
        self.claim_daily()

    def daily_later(self):
        game.after_align = self.claim_daily
        self.daily_by = time.monotonic() + DAILY_LATE_S

    def claim_daily(self):
        if game.ABORT:
            return
        try:
            game.paced(game.DAILY_WAIT_S)
            done = game.daily_by_clicks()
        except Exception as e:
            done = None
            note('daily', 'crashed: %s: %s' % (type(e).__name__, e))
        note('daily', {'claim': 'daily rewards claimed', 'claimed': 'daily rewards already claimed: window closed',
                       False: 'no daily rewards window'}.get(done, 'daily rewards check failed'))

    def post_fishing(self, detail):
        if not self.url:
            return
        try:
            post_shot(self.url, 'Fishing failsafe', EMBED_BAD, '', detail, 'Fishing')
        except Exception as e:
            note('fishing', 'webhook: %s: %s' % (type(e).__name__, e))

    def collect_merchant(self, name, halt):
        say = lambda m: note('merchant', m)
        self._set(phase='going to %s' % name, colour=GOOD)
        moved, got = True, None
        try:
            if self.fisher is not None and not fishing.respawn(halt):
                return
            game.tilt_up(halt)
            got = shop.collect(name, self.wanted, halt, say)
            moved = got is not False
            if not got:
                if not halt() and getattr(self, 'merchant_tries', MERCHANT_TRIES) >= MERCHANT_TRIES:
                    self.tell("Could not open %s's shop" % name, shop.why or 'The shop did not open',
                              EMBED_BAD, 'Merchant')
                elif not halt():
                    say('%s: trying again while %s is here' % (shop.why or 'the shop did not open', name))
                self.close_guis()
                return False
            found, bought = got
            items = ', '.join(found[s] for s in sorted(found)) or 'Could not read the items'
            post_shot(self.url, 'Merchant Items - %s' % name, MERCHANT_COLOURS.get(name, EMBED_GOLD),
                      area='Merchant', fields=[('Item list', items, False),
                                               ('Bought', '\n'.join(bought) or 'Nothing', False)])
            time.sleep(1.0)
            shop.close_shop()
        except Exception as e:
            say('failed - %s: %s' % (type(e).__name__, e))
            self.tell('Merchant collection failed', '`%s: %s`' % (type(e).__name__, e), EMBED_BAD, 'Merchant')
            self.merchant_tries = MERCHANT_TRIES
            try:
                shop.close_shop()
            except Exception:
                pass
            self.close_guis()
        finally:
            if not halt():
                if moved:
                    fishing.respawn(halt)
                game.align_camera(halt)
            if moved:
                self.in_dimension = False
                if self.crack_on and not halt() and (got or self.merchant_tries >= MERCHANT_TRIES):
                    self.use_crack(halt, 'back to Eden\'s dimension after %s' % name)

    def use_crack(self, halt, why):
        say = lambda m: note('eden', m)
        say('using a Portable Crack: %s' % why)
        try:
            ok = shop.use_item(CRACK, halt, say) and self.nap(CRACK_S, halt)
        except Exception as e:
            say('Portable Crack failed - %s: %s' % (type(e).__name__, e))
            self.close_guis()
            ok = False
        self.in_dimension = bool(ok)
        if not ok and not halt():
            self.tell('Portable Crack not used', 'Ensure you have a Portable Crack', EMBED_BAD, 'Eden')
        return self.in_dimension

    def drop_fishing(self, halt, why):
        note('fishing', why)
        self.fisher.pause = self.fisher.hold = False
        try:
            if not self.fisher.at_spot:
                fishing.points.click('fishingShopCloseButton', 0.2)
                fishing.points.leave_dialogue(skip=True)
            else:
                if self.fisher.line_out:
                    self.fisher.reel_in(halt)
                end = time.monotonic() + LATE_RESULT_S
                while time.monotonic() < end and not halt():
                    st = fishing.window_state()
                    if st in ('catch', 'failed'):
                        fishing.close_catch(halt)
                        break
                    if st == 'fish':
                        break
                    time.sleep(0.2)
        except Exception as e:
            note('merchant', 'reeling in failed - %s: %s' % (type(e).__name__, e))
        self.fisher.line_out = False

    def dropped(self):
        return 'merchant' if self.merchant_due is not None else 'pop' if self.pop_due is not None else ''

    def items_turn(self, halt):
        self.between_fish(halt, 'items', 'SC/BR due', self.spend_items)

    def between_fish(self, halt, tag, why, work):
        if self.fisher and self.fisher.at_spot and self.fisher.line_out:
            if not self.fisher.pause:
                self.fisher.pause = True
                note(tag, '%s: landing the fish on the line first' % why)
            return
        if self.fisher and fishing.window_state() == 'catch':
            fishing.close_catch(halt)
        game.INTERRUPT = self.dropped
        try:
            work()
        finally:
            game.INTERRUPT = None
            if self.dropped():
                note(tag, 'stopped for the %s' % self.dropped())
            if self.fisher:
                self.fisher.pause = False
                self.fisher.recast = self.fisher.at_spot and not self.fisher.line_out

    def equip_turn(self):
        aura, say = self.equip_aura, lambda m: note('equip', m)
        halt = lambda: (game.ABORT or self.need_rejoin is not None or self.merchant_due is not None
                        or self.pop_due is not None)

        def logged(since):
            name, at = self.aura_logged
            return bool(name) and clipper.norm(name) == clipper.norm(aura) and at >= max(since, self.run_wall)

        def other(since):
            name, at = self.aura_logged
            same = clipper.norm(name or '') == clipper.norm(aura)
            return name if name and name != '_None_' and not same and at >= max(since, self.run_wall) else None

        self.equip_due = None
        self.equip_busy_at = time.monotonic()
        try:
            on = equip.equip(aura, halt, say, logged, other)
        except Exception as e:
            say('failed - %s: %s' % (type(e).__name__, e))
            self.close_guis()
            on = False
        self.equip_busy_at = time.monotonic()
        if on:
            self.equip_fails = 0
        elif not halt():
            self.equip_fails += 1
            wait = min(EQUIP_RETRY_S * 2 ** (self.equip_fails - 1), 60 * 60)
            self.equip_due = time.monotonic() + wait
            say('trying again in %d minutes' % (wait // 60))
            if self.equip_fails == 1:
                self.tell('Could not equip %s' % aura, 'Trying again in %d minutes' % (wait // 60), EMBED_BAD, 'Aura')
        else:
            self.equip_due = time.monotonic()

    def rune_biome_changed(self, name):
        biome = rune_biome(name, self.rune_biomes)
        if biome is None:
            self.rune_due = None
            return
        self.rune_due, self.rune_tries = time.monotonic() + self.rune_wait, 0
        note('rune', '%s started: a Cursed Rune Fragment in %d s' % (pretty(biome), self.rune_wait))

    def rune_turn(self):
        say = lambda m: note('rune', m)
        biome = rune_biome(self.biome_now, self.rune_biomes)
        if biome is None:
            say('the biome is over (%s now): no Cursed Rune Fragment used' % (pretty(self.biome_now) or 'unknown'))
            self.rune_due = None
            return
        try:
            used = game.item_pass(say=say, terms=(RUNE,))
        except Exception as e:
            used = []
            say('failed - %s: %s' % (type(e).__name__, e))
            self.close_guis()
        if not used and self.dropped():
            return
        self.rune_tries += 1
        if used:
            self.rune_due = None
            self.tell('Used a Cursed Rune Fragment', pretty(biome), EMBED_GOOD, 'Rune')
        elif self.rune_tries < RUNE_TRIES:
            self.rune_due = time.monotonic() + RUNE_RETRY_S
        else:
            self.rune_due = None
            self.tell('Cursed Rune Fragment not used', 'Ensure you have one', EMBED_BAD, 'Rune')

    def pop_biome_changed(self, name):
        biome = rune_biome(name, self.pop_biomes)
        self.pop_due = biome if biome and self.pop_list.get(biome) else None
        self.pop_left = None
        if self.pop_due:
            note('pop', '%s started: popping %s' % (pretty(biome), ', '.join(
                '%s x%d' % (n, a) for n, a in self.pop_list[biome].items())))

    def pop_turn(self, halt):
        biome, self.pop_due = self.pop_due, None
        left = getattr(self, 'pop_left', None)
        left = dict(left[1]) if left and left[0] == biome else dict(self.pop_list.get(biome, {}))
        self.pop_left = None
        say = lambda m: note('pop', m)
        over = lambda: halt() or rune_biome(self.biome_now, {biome}) is None
        used = []
        try:
            for name, amount in list(left.items()):
                if over():
                    break
                n = potions.use(name, amount, over, say)
                if n:
                    used.append('%s x%d' % (name, n))
                left[name] = amount - n if halt() else 0
                if left[name] <= 0:
                    del left[name]
        except Exception as e:
            say('failed - %s: %s' % (type(e).__name__, e))
        finally:
            self.close_guis()
        if left and rune_biome(self.biome_now, {biome}) is None:
            say('%s is over (%s now): stopping' % (pretty(biome), pretty(self.biome_now) or 'unknown'))
        elif left and halt() and not game.ABORT and self.pop_due is None:
            self.pop_left, self.pop_due = (biome, left), biome
            say('interrupted: %s left for after the rejoin' % ', '.join(left))
        if used:
            self.tell('Popped in %s' % pretty(biome), ', '.join(used), biome_colour(biome), 'Pop')
        elif not halt():
            self.tell('Nothing popped in %s' % pretty(biome), 'None of the listed potions were found', EMBED_BAD, 'Pop')

    def selector_landed(self):
        return base_biome(self.biome_now).replace(' ', '') == self.selector_biome.replace(' ', '')

    def selector_turn(self):
        say = lambda m: note('selector', m)
        halt = lambda: game.ABORT or self.need_rejoin is not None or self.merchant_due is not None or self.pop_due
        biome = self.selector_biome
        drive = selector.DRIVES[biome]
        try:
            outcome, wait = selector.use(biome, halt, say)
        except Exception as e:
            outcome, wait = 'refused', None
            say('failed - %s: %s' % (type(e).__name__, e))
            self.close_guis()
        now = time.monotonic()
        self.selector_refused = self.selector_refused + 1 if outcome == 'refused' else 0
        missed = outcome in ('no selector', 'no drive')
        self.selector_missed = getattr(self, 'selector_missed', 0) + 1 if missed else 0
        if missed:
            wait = min(SELECTOR_RETRY_S * 2 ** (self.selector_missed - 1), 60 * 60)
            self.selector_due = now + wait
            what = 'No Biome Selector found in the Inventory' if outcome == 'no selector' else \
                '%s is not in its list (not unlocked yet?)' % drive
            say('%s (miss %d): looking again in %d min' % (what, self.selector_missed, wait // 60))
            if self.selector_missed == SELECTOR_MISSES:
                self.tell('Biome Selector not used', '%s. Trying again every hour at most' % what, EMBED_BAD,
                          'Selector')
        elif self.selector_refused >= SELECTOR_REFUSALS:
            self.selector_due = None
            self.tell('Biome Selector stopped', 'Refused %d times in a row: out of %s?' % (SELECTOR_REFUSALS, drive),
                      EMBED_BAD, 'Selector')
        elif outcome == 'used':
            self.selector_due = now + selector.EVERY_S
            self.tell('Biome Selector used', '%s (%s)' % (pretty(biome), drive), EMBED_GOOD, 'Selector')
        elif outcome == 'recharging':
            self.selector_due = now + wait + ITEM_SPARE_S
            say('next try in %d min' % ((wait + ITEM_SPARE_S) // 60))
        elif outcome == 'stopped':
            self.selector_due = now
        elif outcome == 'refused':
            self.selector_due = now + SELECTOR_REFUSED_S
        elif outcome == 'unstable':
            self.selector_due = now + SELECTOR_RETRY_S
        else:
            self.selector_due = None
            self.tell('Biome Selector stopped', 'Unknown outcome: %s' % outcome, EMBED_BAD, 'Selector')

    def items_due(self):
        now = time.monotonic()
        return (not rune_biome(self.biome_now, HOLD_BIOMES)
                and any(now >= self.item_due.get(t, 0.0) for t in (game.BR, game.SC)))

    def spend_items(self):
        say = lambda m: note('items', m)
        now = time.monotonic()
        due = tuple(t for t in (game.BR, game.SC) if now >= self.item_due.get(t, 0.0))
        if not due:
            return False
        try:
            got = game.item_pass(say=say, terms=due)
            done = time.monotonic()
            cut = self.dropped()
            tried = [t for t in due if t in got or not cut]
            for t in tried:
                self.item_due[t] = done + (ITEM_EVERY_S[t] + ITEM_SPARE_S if t in got else ITEM_RETRY_S)
            for t in set(due) - set(tried):
                say('%s: left for after the %s' % (t, cut))
        except Exception as e:
            for t in due:
                self.item_due[t] = now + ITEM_RETRY_S
            say('failed - %s: %s' % (type(e).__name__, e))
            self.tell('Auto SC + BR failed', '`%s: %s`' % (type(e).__name__, e), EMBED_BAD, 'Auto SC + BR')
            self.close_guis()
            return True
        if not tried:
            return False
        missed = ', '.join(pretty(t) for t in tried if t not in got)
        if got:
            self.tell('Used a ' + ' and a '.join(pretty(t) for t in got), missed and "%s wasn't used" % missed,
                      EMBED_INFO, 'Auto SC + BR')
        else:
            self.tell('Found nothing to use', missed, EMBED_INFO, 'Auto SC + BR')
        if missed:
            self.close_guis()
        return True

    def close_strays(self):
        try:
            if not game.inventory_open():
                return
        except Exception:
            return
        note('menus', 'a window was left open (a cutscene hid it?): closing it')
        self.close_guis()
        if self.fisher:
            self.fisher.line_out = False
            self.fisher.recast = self.fisher.at_spot

    def close_guis(self):
        try:
            if self.fisher and fishing.window_state() in ('catch', 'failed'):
                fishing.close_catch(lambda: game.ABORT)
            game.close_guis()
        except Exception as e:
            note('menus', 'closing menus failed: %s: %s' % (type(e).__name__, e))

    def stop(self):
        note('run', 'Stop pressed')
        self.start_again = False
        self.restart_run = False
        game.ABORT = True
        if self.biome_stop is not None:
            self.biome_stop.set()
        self.phase('stopping', BAD)
        threading.Thread(target=game.release_all, daemon=True).start()

    def close(self):
        if self._closing:
            return
        self._closing = True
        self.start_again = False
        self.restart_run = False
        game.ABORT = True
        if self.biome_stop is not None:
            self.biome_stop.set()
        self.remember()
        self.block_on = False
        try:
            with self.block_lock:
                if self.blocked or self.cache.ours:
                    self._unblock({k for ks in merchant_cache.FILES.values() for k in ks})
        except Exception:
            pass
        try:
            game.disarm()
            game.release_all(focus=False)
        except Exception:
            pass
        os._exit(0)


class Api:
    """JavaScript <-> Python bridge exposed to Edge WebView2 (`window.pywebview.api`)."""

    def __init__(self, engine: MacroEngine):
        self.engine = engine

    def get_state(self):
        return self.engine.build_state()

    def update_cfg(self, patch):
        if isinstance(patch, dict):
            if 'roblox_username' in patch:
                self.engine.apply_roblox_username(patch['roblox_username'])
            with self.engine._lock:
                for k, v in patch.items():
                    if k != 'roblox_username':
                        self.engine.cfg[k] = v
                if 'merchant_on' in patch:
                    self.engine.block_on = bool(patch['merchant_on'])
                    if not self.engine.block_on:
                        self.engine.merchant_detect = False
                self.engine.remember()
        return self.engine.build_state()

    def sync_roblox_profile(self, username):
        self.engine.apply_roblox_username(username, sync=True)
        return self.engine.build_state()

    def resolve_aura(self, typed):
        matched = equip.resolve((typed or '').strip()) if (typed or '').strip() else None
        if matched:
            with self.engine._lock:
                self.engine.cfg['equip_aura'] = matched
                self.engine.remember()
        elif not (typed or '').strip():
            with self.engine._lock:
                self.engine.cfg['equip_aura'] = ''
                self.engine.remember()
        return {'matched': matched}

    def capture_clip_key(self):
        if self.engine._capturing:
            return {'ok': False, 'keys': None}
        self.engine._capturing = True
        try:
            got = clipper.capture_keys()
            if got:
                text = '+'.join(clipper.parse_keys(got))
                with self.engine._lock:
                    self.engine.cfg['clip_keys'] = text
                    self.engine.remember()
                note('clip', 'clip hotkey set to %s' % text)
                return {'ok': True, 'keys': text}
            return {'ok': False, 'keys': None}
        finally:
            self.engine._capturing = False

    def add_buy_item(self, raw):
        raw = (raw or '').strip()
        if raw:
            name = shop.identify(raw, shop.KNOWN_ITEMS) or raw
            with self.engine._lock:
                buy = dict(self.engine.cfg.get('buy_items') or {})
                if name not in buy:
                    buy[name] = {'on': True, 'qty': ''}
                else:
                    buy[name] = {'on': True, 'qty': str(buy[name].get('qty', ''))}
                self.engine.cfg['buy_items'] = buy
                self.engine.remember()
        return self.engine.build_state()

    def toggle_run(self):
        if self.engine.running:
            self.engine.stop()
            return {'ok': True}
        err = self.engine.start()
        if err:
            return {'ok': False, 'error': err}
        return {'ok': True}

    def pick_avatar_photo(self):
        win = self.engine._window
        if win is None:
            return {'ok': False}
        pic_dir = os.path.join(os.path.expanduser('~'), 'Pictures')
        dl_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
        start_dir = pic_dir if os.path.isdir(pic_dir) else (dl_dir if os.path.isdir(dl_dir) else '')
        paths = win.create_file_dialog(
            webview.FileDialog.OPEN,
            directory=start_dir,
            allow_multiple=False,
            file_types=('Image files (*.png;*.jpg;*.jpeg;*.webp;*.bmp)', 'All files (*.*)'),
        )
        if not paths:
            return {'ok': False}
        os.makedirs(game.APP_DIR, exist_ok=True)
        dst = os.path.join(game.APP_DIR, 'avatar_custom.png')
        try:
            Image.open(paths[0]).convert('RGBA').save(dst, 'PNG')
            self.engine._bump_cache_bust()
            return {'ok': True}
        except Exception as e:
            note('ui', 'avatar import failed: %s: %s' % (type(e).__name__, e))
            return {'ok': False}

    def test_webhook(self, url_override=None, server_override=None):
        with self.engine._lock:
            if url_override is not None:
                self.engine.cfg['webhook_url'] = clean_url(url_override)
            if server_override is not None:
                self.engine.cfg['private_server'] = game.tidy_link(server_override)
            if url_override is not None or server_override is not None:
                self.engine.remember()
            url = clean_url(self.engine.cfg_str('webhook_url'))

        if not url.startswith('https://'):
            return {'ok': False, 'error': 'Enter a valid Discord webhook URL first'}
        try:
            embed = {
                'title': 'Webhook Test Successful',
                'description': 'Your Discord webhook is connected and ready to receive alerts.',
                'color': EMBED_GOOD,
                'footer': {'text': '%s | Release v%s' % (TITLE, VERSION)},
            }
            files = {}
            manas = logo_png()
            if manas:
                files['manas.png'] = manas
                embed['thumbnail'] = {'url': 'attachment://manas.png'}
            payload = {
                'content': '',
                'allowed_mentions': {'parse': []},
                'embeds': [embed],
            }
            urllib.request.urlopen(_build_webhook_request(url, payload, files), timeout=20).close()
            note('webhook', 'webhook test succeeded (no biome/server link sent)')
            return {'ok': True}
        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = e.read().decode('utf-8', errors='replace')[:180]
            except Exception:
                pass
            msg = 'Discord rejected (%s): %s' % (e.code, detail or e.reason)
            note('webhook', msg)
            return {'ok': False, 'error': msg}
        except Exception as e:
            msg = '%s: %s' % (type(e).__name__, e)
            note('webhook', 'webhook test failed: ' + msg)
            return {'ok': False, 'error': msg}

    def set_on_top(self, val):
        hwnd = getattr(self.engine, '_hwnd', None) or _find_own_hwnd()
        if hwnd:
            self.engine._hwnd = hwnd
            ok = _set_hwnd_topmost(hwnd, bool(val))
            return {'ok': ok}
        return {'ok': False}

    def open_calibrator(self, mode='all'):
        try:
            mode_arg = str(mode or 'all')
            if getattr(sys, 'frozen', False):
                cmd = [sys.executable, '--calibrate', mode_arg]
                cwd = os.path.dirname(sys.executable)
            else:
                cmd = [sys.executable, os.path.join(HERE_DIR, 'calibrator_ui.py'), mode_arg]
                cwd = HERE_DIR
            subprocess.Popen(cmd, cwd=cwd)
            return {'ok': True}
        except Exception as e:
            note('ui', 'failed to open calibrator: %s: %s' % (type(e).__name__, e))
            return {'ok': False}

    def open_clips(self):
        os.makedirs(clipper.CLIP_DIR, exist_ok=True)
        os.startfile(clipper.CLIP_DIR)
        return {'ok': True}

    def open_data_folder(self):
        os.makedirs(game.APP_DIR, exist_ok=True)
        os.startfile(game.APP_DIR)
        return {'ok': True}

    def open_discord(self):
        webbrowser.open(INVITE)
        return {'ok': True}

    def clear_logs(self):
        with _log_lock:
            _recent_logs.clear()
        return {'ok': True}

    def reset_all_data(self):
        """Wipe user settings, saved coordinates, custom avatar, and biome history for a clean fresh start."""
        if self.engine.running:
            self.engine.stop()
        with self.engine._lock:
            for fname in ('config.json', 'history.jsonl', 'gui_points.json', 'ai_memory.json', 'avatar_custom.png', 'avatar.png'):
                p = os.path.join(game.APP_DIR, fname)
                if os.path.isfile(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            for av in glob.glob(os.path.join(game.APP_DIR, 'avatar_*.png')):
                try:
                    os.remove(av)
                except OSError:
                    pass
            self.engine.cfg = normalize_cfg({})
            self.engine.block_on = False
            self.engine.wanted = {}
            self.engine.pop_list = {}
            self.engine._history.clear()
            self.engine._biome_counts.clear()
            self.engine.rares_count = 0
            self.engine.biome_now = 'NORMAL'
            auto_name, auto_uid = detect_roblox_profile()
            self.engine.player_name = auto_name
            self.engine.roblox_uid = auto_uid
            _QuietHandler.avatar_uid = auto_uid
            self.engine.cache_bust += 1
            self.engine.remember()
        note('config', 'all settings and history reset to factory defaults')
        return self.engine.build_state()


# ================================================================ Single Instance & Entrypoint
SWAP_BAT = r"""@echo off
set sys=%SystemRoot%\System32
set n=0
:wait
"%sys%\tasklist.exe" /FI "PID eq %MMACRO_PID%" 2>nul | "%sys%\find.exe" "%MMACRO_PID%" >nul || goto swap
set /a n+=1
if %n% geq 30 goto swap
"%sys%\PING.EXE" -n 2 127.0.0.1 >nul
goto wait
:swap
set n=0
:again
if "%MMACRO_ZIP%"=="1" (
  "%sys%\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Expand-Archive -Force -LiteralPath $env:MMACRO_NEW -DestinationPath $env:MMACRO_DIR" >nul 2>&1
) else (
  move /y "%MMACRO_NEW%" "%MMACRO_EXE%" >nul 2>&1
)
if not errorlevel 1 goto start
set /a n+=1
if %n% geq 30 goto start
"%sys%\PING.EXE" -n 2 127.0.0.1 >nul
goto again
:start
if "%MMACRO_ZIP%"=="1" del "%MMACRO_NEW%"
start "" "%MMACRO_EXE%"
del "%~f0"
"""

UNPACK_MARKS = ('auras.json', 'eden.png', 'gui_points.json')


def clear_old_unpacks(temp=None, current=None, fresh_s=120):
    current = current or getattr(sys, '_MEIPASS', None)
    temp = temp or tempfile.gettempdir()
    gone = 0
    for d in glob.glob(os.path.join(temp, '_MEI*')):
        if current and os.path.normcase(os.path.abspath(d)) == os.path.normcase(os.path.abspath(current)):
            continue
        if not d.endswith('-old'):
            if not all(os.path.isfile(os.path.join(d, f)) for f in UNPACK_MARKS):
                continue
            core = sorted(glob.glob(os.path.join(d, 'python3*.dll')), key=len, reverse=True)[:1]
            try:
                if not core or time.time() - os.path.getmtime(d) < fresh_s:
                    continue
                os.remove(core[0])
                os.rename(d, d + '-old')
            except OSError:
                continue
            d += '-old'
        shutil.rmtree(d, ignore_errors=True)
        gone += not os.path.exists(d)
    return gone


def _clear_old_unpacks():
    try:
        n = clear_old_unpacks()
        if n:
            note('cleanup', 'deleted %d old unpacked cop%s of MMacro from %%TEMP%%' % (n, 'y' if n == 1 else 'ies'))
    except Exception as e:
        note('cleanup', '%s: %s' % (type(e).__name__, e))


def only_one():
    global _one
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    _one = [k.CreateMutexW(None, False, 'Local\\MMacroHUD')]
    if ctypes.get_last_error() == 183:
        return 'MMacro HUD is already open.'
    user = re.sub(r'[^\w.-]', '_', os.environ.get('USERDOMAIN', '') + '.' + os.environ.get('USERNAME', ''))
    _one.append(k.CreateMutexW(None, False, 'Global\\MMacroHUD-' + user))
    if ctypes.get_last_error() == 183:
        return ('MMacro HUD is already running for this Windows account in another session (another RDP).\n\n'
                'Two macros on one account share Roblox\'s logs and MMacro HUD\'s settings, so each RDP needs its own '
                'Windows account. Log the second RDP into a different account, then open MMacro HUD there.')
    return None


def _focus_existing_mmacro():
    u32 = ctypes.windll.user32
    found = []

    def cb(h, _):
        n = u32.GetWindowTextLengthW(h)
        if n > 0:
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, buf, n + 1)
            if (buf.value == TITLE or buf.value.startswith(TITLE + '  |')) and u32.IsWindowVisible(h):
                found.append(h)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    u32.EnumWindows(WNDENUMPROC(cb), 0)
    if found:
        u32.ShowWindow(found[0], 9)
        u32.SetForegroundWindow(found[0])
        return True
    return False


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == '--calibrate':
        import calibrator_ui
        calibrator_ui.run(sys.argv[2] if len(sys.argv) > 2 else 'all')
        sys.exit(0)
    why = only_one()
    if why:
        if why == 'MMacro HUD is already open.' and _focus_existing_mmacro():
            sys.exit(0)
        ctypes.windll.user32.MessageBoxW(0, why, TITLE, 0x40)
        sys.exit(0)
    threading.Thread(target=_clear_old_unpacks, daemon=True).start()

    srv = start_ui_server()
    port = srv.server_address[1]
    url = 'http://127.0.0.1:%d/ui/index.html' % port

    engine = MacroEngine()
    api = Api(engine)

    window = webview.create_window(
        TITLE,
        url,
        js_api=api,
        width=1160,
        height=740,
        min_size=(960, 620),
        background_color='#050810',
        on_top=False,
    )
    engine._window = window

    def on_shown():
        try:
            hwnd = _find_own_hwnd()
            engine._hwnd = hwnd
            _dark_titlebar_hwnd(hwnd)
        except Exception:
            pass

    window.events.shown += on_shown
    window.events.closing += lambda: engine.remember()
    window.events.closed += engine.close

    ico = os.path.join(HERE_DIR, 'icon.ico')
    try:
        webview.start(gui='edgechromium', icon=ico if os.path.isfile(ico) else None, debug=False)
    except Exception:
        webview.start(debug=False)


if __name__ == '__main__':
    main()
