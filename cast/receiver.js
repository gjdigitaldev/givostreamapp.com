/**
 * GiVo Stream — custom Chromecast receiver (CAF v3 + hls.js).
 *
 * WHY THIS EXISTS
 * ---------------
 * The Default Media Receiver's Shaka player cannot START our live IPTV relay:
 *   - raw MPEG-TS-HLS → decode/demux error (idleReason=4),
 *   - fMP4-CMAF (even with +program_date_time + a master playlist carrying
 *     CODECS) → fetches every segment but stays `loading`, never `playing`.
 * hls.js demuxes MPEG-TS-HLS natively (transmux → fMP4 in JS → MSE), which is
 * exactly the gap. So this receiver hands live HLS to hls.js and lets CAF own
 * only the session / state / metadata UI.
 *
 * INTEGRATION MODEL
 * -----------------
 * <cast-media-player> renders a <video> element and CAF's PlayerManager binds
 * to it. We intercept LOAD: for HLS content we create an Hls() instance,
 * attachMedia(<video>) (hls.js creates a MediaSource and sets video.src to a
 * blob: URL), loadSource(url), and on MANIFEST_PARSED we rewrite the request's
 * contentUrl to that SAME blob URL before resolving — so CAF's player binds to
 * hls.js's MediaSource instead of re-fetching the manifest itself (no fight
 * over the media element). Non-HLS falls through to CAF's default player.
 *
 * The relay sends MPEG-TS-HLS (a bare media playlist, `live.m3u8`) for this
 * receiver — hls.js's most battle-tested path. (The fMP4 + master-playlist
 * packaging is only for the Default Media Receiver fallback.)
 */
'use strict';

var NAMESPACE = '[GiVoReceiver]';
function log(msg) { try { console.log(NAMESPACE + ' ' + msg); } catch (e) {} }

var context = cast.framework.CastReceiverContext.getInstance();
var playerManager = context.getPlayerManager();

// hls.js instance for the CURRENT media (recreated on every LOAD / channel switch).
var hls = null;
// Bounded recovery counters, reset per media.
var netRetries = 0;
var mediaRetries = 0;
var MAX_NET_RETRIES = 8;     // flaky IPTV / relay reconnects — be patient
var MAX_MEDIA_RETRIES = 4;

// --- hls.js config, tuned for LIVE IPTV on memory-limited Chromecast hardware.
var HLS_CONFIG = {
  // Transmux/parse off the main thread so the Cast UI stays responsive. If an
  // old Chromecast lacks Worker support hls.js auto-falls-back to inline.
  enableWorker: true,
  lowLatencyMode: false,        // our relay is standard live HLS, not LL-HLS

  // Live edge tracking. Segments are ~2 s; stay ~3 back (~6 s) so a brief
  // network dip doesn't underrun, and cap catch-up latency.
  liveSyncDurationCount: 3,
  liveMaxLatencyDurationCount: 12,
  liveDurationInfinity: true,   // report an infinite (live) seekable range

  // Buffer bounds — keep modest for Chromecast RAM.
  backBufferLength: 30,
  maxBufferLength: 30,
  maxMaxBufferLength: 60,
  maxBufferSize: 60 * 1000 * 1000,   // 60 MB

  // Generous retries — IPTV providers + the relay reconnect a lot.
  manifestLoadingMaxRetry: 6,
  manifestLoadingRetryDelay: 1000,
  manifestLoadingMaxRetryTimeout: 64000,
  levelLoadingMaxRetry: 6,
  levelLoadingRetryDelay: 1000,
  fragLoadingMaxRetry: 8,
  fragLoadingRetryDelay: 1000,
  fragLoadingMaxRetryTimeout: 64000,

  startLevel: -1,               // single-variant relay; -1 = auto
  testBandwidth: false
};

function getVideoElement() {
  // <cast-media-player> renders its <video> into the light DOM.
  var vids = document.getElementsByTagName('video');
  return (vids && vids.length) ? vids[0] : null;
}

function destroyHls() {
  if (hls) {
    try { hls.destroy(); } catch (e) {}
    hls = null;
  }
  netRetries = 0;
  mediaRetries = 0;
  isLiveContent = true;   // default safe for the next media until LEVEL_LOADED says otherwise
}

// --- Keep LIVE playback playing (BUG A). The receiver was dropping into a paused
//     state ~12 s in and sitting there until the user pressed Play on the remote.
//     A GiVo relay is live TV: there's no seek/rewind buffer to pause into, so any
//     non-live pause is spurious and should immediately resume. We install ONE set
//     of listeners per <video> element and re-issue play() on pause/waiting/stalled
//     (debounced so a genuinely stalled network doesn't spin play() in a tight
//     loop). The interval watchdog is the backstop for a pause with no event.
var autoplayGuardEl = null;
var autoplayResumeTimer = null;
// LIVE-only guard (T576). A GiVo relay is live TV by default → any pause is
// spurious and we re-issue play(). But a VOD relay (a movie/recording) is a
// real seekable asset where a user PAUSE must STICK. `isLiveContent` starts true
// (safe for live) and flips false when hls.js reports a non-live playlist
// (`details.live === false`, set on LEVEL_LOADED), disarming the auto-resume.
var isLiveContent = true;
function resumeIfPaused(reason) {
  var v = autoplayGuardEl;
  if (!v || v.ended || !hls || !isLiveContent) return;
  if (autoplayResumeTimer) return;
  autoplayResumeTimer = setTimeout(function () {
    autoplayResumeTimer = null;
    if (v.paused && !v.ended && hls && isLiveContent) {
      log('auto-resume (' + reason + ')');
      try { v.play(); } catch (e) {}
    }
  }, 400);
}
function installAutoplayGuard(videoEl) {
  if (!videoEl || videoEl === autoplayGuardEl) return;
  autoplayGuardEl = videoEl;
  videoEl.addEventListener('pause', function () { resumeIfPaused('pause'); });
  videoEl.addEventListener('waiting', function () { resumeIfPaused('waiting'); });
  videoEl.addEventListener('stalled', function () { resumeIfPaused('stalled'); });
}
// Watchdog backstop: if the element is paused but has buffered data ready, nudge
// it back to playing. `readyState >= HAVE_CURRENT_DATA` (2) means there's a frame
// to show, so this never fights a genuine underrun (that goes through 'waiting').
// LIVE only — a VOD pause is intentional.
setInterval(function () {
  var v = autoplayGuardEl;
  if (v && hls && isLiveContent && v.paused && !v.ended && v.readyState >= 2) {
    log('watchdog auto-resume (paused with buffer)');
    try { v.play(); } catch (e) {}
  }
}, 3000);

function looksLikeHls(url, contentType) {
  if (contentType && /mpegurl|vnd\.apple/i.test(contentType)) return true;
  if (!url) return false;
  return /\.m3u8(\?|$)/i.test(url) || /m3u8\?/i.test(url);
}

// --- LOAD interceptor: take over HLS with hls.js; pass everything else through.
playerManager.setMessageInterceptor(
  cast.framework.messages.MessageType.LOAD,
  function (request) {
    var media = request.media || {};
    var url = media.contentUrl || media.contentId;

    if (!looksLikeHls(url, media.contentType)) {
      log('LOAD (default player): ' + url);
      return request;
    }
    if (!Hls.isSupported()) {
      // No MSE/hls.js — let CAF's native player try (will likely fail on TS,
      // but that surfaces a clean error to the sender rather than a hang).
      log('LOAD: hls.js unsupported on this device — falling back to native');
      return request;
    }
    var videoEl = getVideoElement();
    if (!videoEl) {
      log('LOAD: no <video> element yet — falling back to native');
      return request;
    }

    log('LOAD (hls.js): ' + url);
    // A GiVo Stream relay is always a live channel — CAF must autoplay and stay
    // playing. `request.autoplay` guarantees CAF resumes after LOAD; the
    // per-element guard + watchdog (BUG A) re-issue play() if the receiver ever
    // drops into a paused state on its own.
    request.autoplay = true;
    installAutoplayGuard(videoEl);
    destroyHls();
    hls = new Hls(HLS_CONFIG);

    return new Promise(function (resolve, reject) {
      var started = false;

      hls.on(Hls.Events.MANIFEST_PARSED, function () {
        if (started) return;
        started = true;
        log('MANIFEST_PARSED levels=' + (hls.levels ? hls.levels.length : '?'));
        // Bind CAF to the SAME MediaSource hls.js created (video.src is now a
        // blob: URL) so CAF's player doesn't re-fetch and clobber hls.js.
        request.media.contentUrl = videoEl.src;
        try { videoEl.play(); } catch (e) {}
        resolve(request);
      });

      // Live-vs-VOD detection (T576): the relay emits a VOD/EVENT playlist for a
      // movie/recording (`details.live === false`) and a sliding-window LIVE
      // playlist for a channel. Disarm the auto-resume guard for VOD so a user
      // pause sticks. `details.live` is only reliable once a level is loaded.
      hls.on(Hls.Events.LEVEL_LOADED, function (event, data) {
        if (data && data.details && data.details.live === false) {
          if (isLiveContent) log('LEVEL_LOADED → VOD (autoplay guard disarmed)');
          isLiveContent = false;
        }
      });

      hls.on(Hls.Events.ERROR, function (event, data) {
        handleHlsError(data, function () { return started; }, reject);
      });

      hls.attachMedia(videoEl);
      hls.loadSource(url);
    });
  });

// --- Bounded, staged error recovery (hls.js's recommended pattern).
function handleHlsError(data, isStarted, rejectInitial) {
  log('ERROR type=' + data.type + ' details=' + data.details + ' fatal=' + data.fatal);
  if (!data.fatal) return;

  if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
    if (netRetries++ < MAX_NET_RETRIES) {
      log('network fatal — startLoad retry ' + netRetries + '/' + MAX_NET_RETRIES);
      setTimeout(function () { if (hls) { try { hls.startLoad(); } catch (e) {} } }, 1000);
      return;
    }
  } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
    if (mediaRetries++ < MAX_MEDIA_RETRIES) {
      log('media fatal — recoverMediaError ' + mediaRetries + '/' + MAX_MEDIA_RETRIES);
      try { hls.recoverMediaError(); } catch (e) {}
      return;
    }
  }

  // Unrecoverable.
  log('unrecoverable fatal — giving up');
  destroyHls();
  if (!isStarted()) {
    // Initial load never started → reject so the sender sees a load failure
    // (our CastMediaClientListener → honest toast + local rebuild).
    rejectInitial(new Error('hls.js fatal: ' + data.details));
  } else {
    // Mid-playback → surface an error status; the sender's mediaStatus listener
    // picks up the idle/error and recovers.
    try {
      context.sendError && context.sendError('hls.js fatal: ' + data.details);
    } catch (e) {}
  }
}

// --- Lifecycle cleanup: drop hls.js when media stops so a stale instance can't
//     keep pulling the relay after the session ends / channel switches.
playerManager.addEventListener(
  cast.framework.events.EventType.MEDIA_FINISHED, function () {
    log('MEDIA_FINISHED — destroying hls.js');
    destroyHls();
  });
// **Don't let the receiver LINGER after the sender leaves (T563 reliability).**
// A session held open after the app disconnects gets AUTO-RESUMED stale on the
// next cast ("connected but nothing plays", only cleared by a force-quit). When
// the LAST sender disconnects, drop hls.js and stop the receiver so the next
// cast starts fresh. Live playback keeps a sender connected, so this only fires
// on a genuine disconnect, never mid-stream.
context.addEventListener(cast.framework.system.EventType.SENDER_DISCONNECTED, function () {
  var remaining = 0;
  try { remaining = context.getSenders() ? context.getSenders().length : 0; } catch (e) {}
  log('SENDER_DISCONNECTED — remaining senders=' + remaining);
  if (remaining === 0) {
    destroyHls();
    try { context.stop(); } catch (e) {}
  }
});

// --- Start. `maxInactivity` is a BACKSTOP only — a connected sender's heartbeats
//     + live media activity keep the session alive indefinitely while casting, so
//     5 min of true idle (no sender, no media) is safe and prevents the
//     zombie-session-holds-old-connection problem (the SENDER_DISCONNECTED handler
//     above is the immediate terminate; this catches any edge it misses).
var options = new cast.framework.CastReceiverOptions();
options.maxInactivity = 300;   // 5 min idle grace (was 6 h — that was the zombie cause)
context.start(options);
log('receiver started (hls.js '
    + (typeof Hls !== 'undefined' && Hls.version ? Hls.version : '?')
    + ', supported=' + (typeof Hls !== 'undefined' ? Hls.isSupported() : false) + ')');
