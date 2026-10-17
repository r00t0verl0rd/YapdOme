/* TRIAD Pixel Puppet: presentation only; app.js owns all speech and turn state. */
(() => {
  'use strict';
  const engine = window.YapPixelEngine;
  const STORAGE_KEY = 'YapdOme.pixel-puppet.v1';
  const ids = ['norman', 'glitch', 'jessie'];
  const labels = {neutral:'Спокойствие', joy:'Радость', laugh:'Смех', angry:'Злость', surprise:'Удивление', skeptic:'Скепсис', sad:'Грусть', smug:'Ухмылка', focus:'Фокус', confused:'Недоумение'};
  const hasMood = v => typeof v === 'string' && Object.hasOwn(labels, v);
  const validMood = v => v === 'auto' || hasMood(v);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const $ = id => document.getElementById(id);
  const text = (node, value) => { if (node.textContent !== value) node.textContent = value; };
  function readSettings() {
    const result = {enabled:true, fps:12, moods:['auto', 'auto', 'auto']};
    try {
      const v = JSON.parse(localStorage.getItem(STORAGE_KEY));
      if (!v || typeof v !== 'object' || Array.isArray(v)) return result;
      if (typeof v.enabled === 'boolean') result.enabled = v.enabled;
      if ([12, 20, 30].includes(v.fps)) result.fps = v.fps;
      if (Array.isArray(v.moods) && v.moods.length === 3)
        result.moods = result.moods.map((m, i) => validMood(v.moods[i]) ? v.moods[i] : m);
    } catch (_) { /* Private browsing or corrupt storage: keep safe defaults. */ }
    return result;
  }
  const settings = readSettings();
  function save() { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(settings)); } catch (_) {} }
  function context() {
    let audio = null, current = null, cast = [];
    try { if (typeof speech !== 'undefined') audio = speech; } catch (_) {}
    try { if (typeof state !== 'undefined' && !state.paused) current = state.current; } catch (_) {}
    try { if (typeof defs !== 'undefined') cast = defs; } catch (_) {}
    const speaker = Number.isInteger(audio?.audibleAgent) && audio.audibleAgent >= 0 && audio.audibleAgent < 3 ? audio.audibleAgent : null;
    return {audio, current, cast, speaker};
  }
  // Bounded lexical hints, not emotion recognition from audio.
  function heuristic(value) {
    const s = typeof value === 'string' ? value.slice(0, 2048).toLowerCase() : '';
    if (/ха-ха|хаха|ахаха|\blol\b/.test(s)) return 'laugh';
    if (/не понимаю|непонятно|запутал|confus/.test(s)) return 'confused';
    if (/груст|жаль|печаль|\bsad\b/.test(s)) return 'sad';
    if (/злюсь|бесит|ярост|angry/.test(s)) return 'angry';
    if (/серьёзно\?|сомнева|вряд ли|really\?/.test(s)) return 'skeptic';
    if (/(?:^|[^\p{L}])(?:ура|отлично|здорово|радост\p{L}*|great|happy)(?=$|[^\p{L}])/u.test(s)) return 'joy';
    if (/невероятно|(?:^|[^\p{L}])(?:ого|wow)(?=$|[^\p{L}])|!{2,}/u.test(s)) return 'surprise';
    return 'neutral';
  }
  function autoMood(qwen, line) {
    if (qwen === 'neutral') return {mood:heuristic(line), source:'эвристика текста'};
    if (qwen === 'calm') return {mood:'neutral', source:'профиль голоса'};
    if (qwen === 'excited') return {mood:/!{2,}|(?:^|[^\p{L}])(?:ого|wow)(?=$|[^\p{L}])/iu.test(line) ? 'surprise' : 'joy', source:'профиль голоса'};
    if (qwen === 'dramatic') return {mood:'surprise', source:'профиль голоса'};
    if (hasMood(qwen)) return {mood:qwen, source:'профиль голоса'};
    return {mood:heuristic(line), source:'эвристика текста'};
  }
  let root = null, booted = false, raf = null, lastFrame = -Infinity;
  let onscreen = true, observer = null, speaker = null, entry = null;
  let speechStart = 0, snapshot = {mood:'neutral', source:'эвристика текста'};
  let meter = null, samples = null;
  const agents = [];
  const reduced = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : {matches:false};
  function running() { return booted && settings.enabled && !document.hidden && onscreen; }
  function wantsFrame() {
    return running() && (!reduced.matches || speaker !== null || agents.some(a => a.event));
  }
  function schedule() {
    if (!wantsFrame()) { if (raf !== null) cancelAnimationFrame(raf); raf = null; return; }
    if (raf === null) raf = requestAnimationFrame(frame);
  }
  function frame(now) {
    raf = null;
    if (running() && now - lastFrame >= 1000 / settings.fps) {
      const dt = Math.min(.1, Math.max(0, (now - lastFrame) / 1000));
      lastFrame = now;
      render(now, Number.isFinite(dt) ? dt : 0);
    }
    schedule();
  }
  function level(ctx, now) {
    if (speaker === null) return 0;
    if (entry?.audioMode === 'browser') {
      const t = (now - speechStart) / 1000;
      return clamp(.3 + .3 * Math.sin(t * 15) + .24 * Math.sin(t * 29), 0, 1);
    }
    const analyser = ctx.audio?.audioMeter;
    if (!analyser || typeof analyser.getFloatTimeDomainData !== 'function') return 0;
    const size = analyser.fftSize;
    if (!Number.isInteger(size) || size < 32 || size > 32768) return 0;
    if (meter !== analyser || samples?.length !== size) { meter = analyser; samples = new Float32Array(size); }
    try {
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (let i = 0; i < samples.length; i++) {
        if (!Number.isFinite(samples[i])) return 0;
        sum += samples[i] * samples[i];
      }
      return clamp(Math.sqrt(sum / samples.length) * 4, 0, 1);
    } catch (_) { return 0; }
  }
  function render(now, dt) {
    const ctx = context();
    // Check actual ownership on every rendered frame as well as explicit parent sync.
    if (ctx.speaker !== speaker || (ctx.audio?.audibleEntry || null) !== entry) capture(ctx, now);
    const amplitude = settings.enabled ? level(ctx, now) : 0;
    for (const a of agents) {
      if (a.event && now >= a.event.until) a.event = null;
      const speaking = speaker === a.index;
      const thinking = !speaking && ctx.current?.agent === a.index;
      const automatic = speaking ? snapshot : {mood:thinking ? 'focus' : 'neutral', source:thinking ? 'подготовка ответа' : 'авто'};
      const chosen = settings.moods[a.index] !== 'auto' ? {mood:settings.moods[a.index], source:'вручную'} :
        a.event?.mood ? {mood:a.event.mood, source:'временная реакция'} : automatic;
      const target = {...engine.EMOTIONS[chosen.mood]};
      // Listening gaze takes priority over optional externally requested gaze.
      const gaze = speaker !== null && !speaking ? Math.sign(speaker - a.index) * .85 : a.event?.direction;
      if (gaze !== undefined) { target.gaze = gaze; target.yaw = gaze * .45; }
      for (const key of engine.keys) {
        if (reduced.matches) { a.pose[key] = target[key]; a.velocity[key] = 0; continue; }
        // Substeps keep the original 88/17 spring stable even at 12 fps.
        const steps = Math.max(1, Math.ceil(dt * 120)), h = dt / steps;
        for (let n = 0; n < steps; n++) {
          a.velocity[key] += ((target[key] - a.pose[key]) * 88 - a.velocity[key] * 17) * h;
          a.pose[key] += a.velocity[key] * h;
        }
      }
      a.level = speaking && settings.enabled ? amplitude : 0;
      // Preset open/round must never hold the mouth open during silence or STOP.
      const pose = {...a.pose, open:0, round:a.level > 0 ? a.pose.round : 0};
      const blinkPhase = (now + a.index * 700) % 4300;
      const blink = !reduced.matches && blinkPhase < 160 ? Math.sin(Math.PI * blinkPhase / 160) : 0;
      const pixels = engine.draw(a.id, pose, {t:reduced.matches ? 0 : now / 1000, talk:a.level, blink});
      for (let i = 0; i < pixels.length; i++) {
        if (pixels[i] !== a.last[i]) { a.leds[i].dataset.v = String(pixels[i]); a.last[i] = pixels[i]; }
      }
      const name = String(ctx.cast?.[a.index]?.name || a.id);
      a.grid.setAttribute('aria-label', `${name}: ${labels[chosen.mood]}`);
      const mode = !settings.enabled ? 'ВЫКЛ' : speaking ? (entry?.audioMode === 'browser' ? 'ГОВОРИТ · имитация' : 'ГОВОРИТ · RMS') : thinking ? 'ДУМАЕТ' : speaker !== null ? 'СЛУШАЕТ' : 'ГОТОВ';
      const status = `${name} · ${mode} · ${labels[chosen.mood]} · ${chosen.source}`;
      text(a.status, status);
      a.status.title = status;
      a.mood = chosen.mood; a.source = chosen.source; a.speaking = speaking;
    }
  }
  function capture(ctx, now) {
    speaker = ctx.speaker;
    entry = ctx.audio?.audibleEntry || null;
    speechStart = now;
    const line = typeof entry?.text === 'string' ? entry.text.slice(0, 2048) : '';
    snapshot = autoMood(entry?.config?.qwenEmotion, line);
    meter = null; samples = null;
  }
  function mountControls() {
    const cards = $('cards');
    if (!cards) return;
    for (const a of agents) {
      const slot = cards.children[a.index]?.querySelector('.emotion-slot');
      if (slot && a.controls.parentElement !== slot) slot.append(a.controls);
      a.controls.hidden = !settings.enabled;
    }
  }
  function sync() {
    if (!booted) boot();
    if (!booted) return;
    const now = performance.now(), ctx = context();
    if (ctx.speaker !== speaker || (ctx.audio?.audibleEntry || null) !== entry) capture(ctx, now);
    root.classList.toggle('pixel-enabled', settings.enabled);
    mountControls();
    // Even while disabled/hidden, discard the old speech level synchronously.
    if (!running()) for (const a of agents) { a.level = 0; a.speaking = speaker === a.index; }
    if (running() || !settings.enabled) render(now, 0);
    schedule();
  }
  function receive(evt) {
    if (!evt || typeof evt !== 'object' || Array.isArray(evt)) return false;
    const allowed = evt.type === 'gaze' ? ['type', 'agent', 'direction', 'duration'] :
      ['emotion', 'reaction'].includes(evt.type) ? ['type', 'agent', 'emotion', 'duration'] : null;
    if (!allowed || Object.keys(evt).some(k => !allowed.includes(k))) return false;
    const index = Number.isInteger(evt.agent) ? evt.agent : ids.indexOf(evt.agent);
    if (index < 0 || index > 2 || !agents[index]) return false;
    const duration = evt.duration === undefined ? 2000 : evt.duration;
    if (typeof duration !== 'number' || !Number.isFinite(duration) || duration < 100 || duration > 10000) return false;
    if (evt.type === 'gaze') {
      if (typeof evt.direction !== 'number' || !Number.isFinite(evt.direction) || Math.abs(evt.direction) > 1) return false;
      agents[index].event = {direction:evt.direction, until:performance.now() + duration};
    } else {
      if (!hasMood(evt.emotion)) return false;
      agents[index].event = {mood:evt.emotion, until:performance.now() + duration};
    }
    sync(); return true;
  }
  function boot() {
    if (booted || !engine || engine.W !== 48 || engine.H !== 48) return;
    root = $('liveAvatars');
    const tiles = root ? [...root.querySelectorAll('.live-tile')] : [];
    if (tiles.length !== 3 || tiles.some(t => !t.querySelector('.hud-portrait'))) return;
    tiles.forEach((tile, index) => {
      const portrait = tile.querySelector('.hud-portrait');
      portrait.classList.add('pixel-portrait');
      const grid = document.createElement('div'); grid.className = 'pixel-grid'; grid.setAttribute('role', 'img');
      const fragment = document.createDocumentFragment(), leds = [];
      for (let i = 0; i < 48 * 48; i++) {
        const led = document.createElement('i'); led.className = 'pixel-led'; led.dataset.v = '0';
        fragment.append(led); leds.push(led);
      }
      grid.append(fragment); portrait.append(grid);
      const controls = document.createElement('div'); controls.className = 'pixel-controls';
      const label = document.createElement('label'); label.className = 'pixel-label'; label.textContent = 'Мимика '; 
      const select = document.createElement('select'); select.className = 'pixel-mood';
      for (const mood of ['auto', ...Object.keys(labels)]) {
        const option = document.createElement('option'); option.value = mood; option.textContent = mood === 'auto' ? 'Авто' : labels[mood]; select.append(option);
      }
      select.value = settings.moods[index];
      select.addEventListener('change', () => {
        if (!validMood(select.value)) return;
        settings.moods[index] = select.value; save(); sync();
      });
      const status = document.createElement('span'); status.className = 'pixel-status';
      label.append(select); controls.append(label, status);
      agents.push({id:ids[index], index, grid, leds, status, controls, last:new Uint8Array(2304),
        pose:{...engine.EMOTIONS.neutral}, velocity:Object.fromEntries(engine.keys.map(k => [k, 0])), event:null, level:0});
    });
    const enabled = $('pixelPuppetEnabled'), fps = $('pixelPuppetFps');
    if (enabled) {
      enabled.checked = settings.enabled;
      enabled.addEventListener('change', () => { settings.enabled = !!enabled.checked; save(); sync(); });
    }
    if (fps) {
      fps.value = String(settings.fps);
      fps.addEventListener('change', () => {
        const value = Number(fps.value); if (![12, 20, 30].includes(value)) return;
        settings.fps = value; save(); sync();
      });
    }
    if (window.IntersectionObserver) {
      observer = new IntersectionObserver(entries => { onscreen = entries.some(e => e.isIntersecting); sync(); });
      observer.observe(root);
    }
    document.addEventListener('visibilitychange', sync);
    reduced.addEventListener?.('change', sync);
    booted = true; sync();
  }
  window.YapdOmePixel = {
    sync, receive, boot, mountControls, version:'triad-1.0', resolution:[48, 48], storageKey:STORAGE_KEY,
    getStatus:() => ({enabled:settings.enabled, fps:settings.fps, speaker,
      agents:agents.map(a => ({id:a.id, mood:a.mood, source:a.source, level:a.level, speaking:a.speaking}))})
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once:true});
  else boot();
})();
