#!/usr/bin/env python3
"""Combined demo server for the GiVo marketing rig on 127.0.0.1:8799.

Serves, from /tmp/demosite:
  - static files (demo.m3u, demo-epg.xml, logos/, posters/, backdrops/, hls/, epthumbs/)
  - a mock Xtream Codes panel: /player_api.php (auth blob + VOD/series actions)
  - /movie/<u>/<p>/<id>.<ext> and /series/<u>/<p>/<epid>.<ext> with HTTP Range
    support (the VOD pipeline byte-seeks), mapped to the Blender source films
    via catalog.json's stream_map.
Content types are fictional demo data only. Run: python3 demo_server.py
"""
import json, os, re, time, email.utils
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

ROOT = "/tmp/demosite"
ROOT_REAL = os.path.realpath(ROOT)
CAT = json.load(open(f"{ROOT}/catalog.json"))
STREAM_RE = re.compile(r"^/(?:movie|series)/[^/]*/[^/]*/(\w+)\.\w+$")

# --- Live HLS pacing (fixes the runaway timeshift spool) --------------------
# The pre-generated per-channel playlists list every segment at once with an
# ENDLIST (VOD style), so a live recorder downloads the whole loop INSTANTLY off
# this local server and races far ahead of real time — defeating the app's
# rolling-window cap and ballooning tmp/givo_dvr/recording.ts to 100s of GB in
# the simulator. Serve the "live" playlist as a REAL-TIME sliding window: one new
# segment becomes available every SEGDUR wall-clock seconds, so the recorder is
# paced at ~1x exactly like a real provider and the 3-hour cap holds.
HLS_IDX_RE = re.compile(r"^/hls/([^/]+)/index\.m3u8$")
HLS_SEG_RE = re.compile(r"^/hls/([^/]+)/seg-(\d+)\.ts$")
SEGDUR = 6.0          # seconds per segment (matches the generated segments)
HLS_WINDOW = 6        # segments advertised in the live window (~36 s)
_seg_count = {}

def channel_seg_count(chan):
    if chan not in _seg_count:
        d = os.path.join(ROOT, "hls", chan)
        try:
            _seg_count[chan] = len([f for f in os.listdir(d)
                                    if re.match(r"seg\d+\.ts$", f)])
        except OSError:
            _seg_count[chan] = 0
    return _seg_count[chan]

def live_playlist_bytes(chan):
    n = channel_seg_count(chan)
    if n == 0:
        return None
    cur = int(time.time() / SEGDUR)           # live edge advances 1 per SEGDUR s
    first = max(0, cur - HLS_WINDOW + 1)
    out = ["#EXTM3U", "#EXT-X-VERSION:3",
           f"#EXT-X-TARGETDURATION:{int(SEGDUR)}",
           f"#EXT-X-MEDIA-SEQUENCE:{first}"]
    for seq in range(first, cur + 1):
        out.append(f"#EXTINF:{SEGDUR:.6f},")
        out.append(f"seg-{seq}.ts")           # unique per seq → mapped to the looped file
    return ("\n".join(out) + "\n").encode()

MIME = {".m3u8": "application/vnd.apple.mpegurl", ".ts": "video/mp2t",
        ".m3u": "audio/x-mpegurl", ".xml": "application/xml",
        ".png": "image/png", ".jpg": "image/jpeg", ".json": "application/json",
        ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".mov": "video/quicktime"}

def user_info_blob():
    now = int(time.time())
    return {
        "user_info": {"username": "", "password": "", "message": "", "auth": 1,
                      "status": "Active", "exp_date": str(now + 86400 * 365),
                      "is_trial": "0", "active_cons": "0", "created_at": str(now - 86400 * 200),
                      "max_connections": "2", "allowed_output_formats": ["m3u8", "ts"]},
        "server_info": {"url": "127.0.0.1", "port": "8799", "https_port": "8799",
                        "server_protocol": "http", "rtmp_port": "0",
                        "timezone": "America/New_York", "timestamp_now": now,
                        "time_now": time.strftime("%Y-%m-%d %H:%M:%S")},
    }

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        with open(f"{ROOT}/server.log", "a") as f:
            f.write("%s %s\n" % (self.address_string(), fmt % args))

    def send_json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path):
        try:
            size = os.path.getsize(path)
        except OSError:
            self.send_error(404)
            return
        rng = self.headers.get("Range")
        ext = os.path.splitext(path)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        start, end = 0, size - 1
        status = 200
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
            if m:
                s, e = m.group(1), m.group(2)
                if s:
                    start = int(s)
                    end = int(e) if e else size - 1
                elif e:  # suffix range
                    start = max(0, size - int(e))
                end = min(end, size - 1)
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Last-Modified", email.utils.formatdate(os.path.getmtime(path), usegmt=True))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 16, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/player_api.php":
            q = parse_qs(u.query)
            action = q.get("action", [""])[0]
            if action == "get_vod_categories":
                return self.send_json(CAT["vod_categories"])
            if action == "get_series_categories":
                return self.send_json(CAT["series_categories"])
            if action == "get_vod_streams":
                return self.send_json(CAT["vod_streams"])
            if action == "get_series":
                return self.send_json(CAT["series"])
            if action == "get_vod_info":
                vid = q.get("vod_id", [""])[0]
                return self.send_json(CAT["vod_info"].get(vid, {"info": {}}))
            if action == "get_series_info":
                sid = q.get("series_id", [""])[0]
                return self.send_json(CAT["series_info"].get(sid, {"info": {}, "episodes": {}}))
            if action in ("get_live_categories", "get_live_streams"):
                return self.send_json([])
            return self.send_json(user_info_blob())
        m = STREAM_RE.match(u.path)
        if m:
            src = CAT["stream_map"].get(m.group(1))
            if src:
                return self.send_file(src)
            self.send_error(404)
            return
        # Live HLS = a real-time sliding window (paced). A catchup fetch carries a
        # time param → fall through to the full static archive so scrubbing works.
        mi = HLS_IDX_RE.match(u.path)
        if mi and not any(k in parse_qs(u.query)
                          for k in ("utc", "start", "lutc", "t", "offset")):
            body = live_playlist_bytes(mi.group(1))
            if body is not None:
                self.send_response(200)
                self.send_header("Content-Type", MIME[".m3u8"])
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
                return
        ms = HLS_SEG_RE.match(u.path)
        if ms:
            n = channel_seg_count(ms.group(1))
            if n:
                idx = int(ms.group(2)) % n
                return self.send_file(os.path.join(ROOT, "hls", ms.group(1), f"seg{idx:03d}.ts"))
            self.send_error(404)
            return
        # static
        rel = os.path.normpath(u.path).lstrip("/")
        path = os.path.join(ROOT, rel)
        if os.path.isfile(path) and os.path.realpath(path).startswith(ROOT_REAL):
            return self.send_file(path)
        self.send_error(404)

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8799), H).serve_forever()
