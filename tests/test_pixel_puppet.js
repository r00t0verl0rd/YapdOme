'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const engine = require('../frontend/animation/pixel-puppet-engine.js');
const adapter = fs.readFileSync(path.join(__dirname, '../frontend/animation/pixel-puppet.js'), 'utf8');

test('real engine: 48×48 literal LEDs 0..3, three distinct robots and expressions', () => {
  assert.equal(engine.W, 48); assert.equal(engine.H, 48);
  assert.equal(Object.keys(engine.EMOTIONS).length, 10);
  const faces = new Set();
  for (const id of ['norman', 'glitch', 'jessie']) {
    const expressions = new Set();
    for (const pose of Object.values(engine.EMOTIONS)) {
      const pixels = engine.draw(id, pose, {t:0, talk:0, blink:0});
      assert.ok(pixels instanceof Uint8Array);
      assert.equal(pixels.length, 2304);
      assert.ok(pixels.every(v => Number.isInteger(v) && v >= 0 && v <= 7));
      assert.ok(new Set(pixels).size >= 5, `${id}: layered material palette`);
      expressions.add(Buffer.from(pixels).toString('base64'));
    }
    assert.ok(expressions.size >= 8, `${id}: distinct expressions`);
    faces.add(Buffer.from(engine.draw(id, engine.EMOTIONS.neutral)).toString('base64'));
    assert.notDeepEqual(engine.draw(id, {}, {talk:0}), engine.draw(id, {}, {talk:1}));
  }
  assert.equal(faces.size, 3);
});

class Element {
  constructor(tag = 'div') {
    this.tag = tag; this.children = []; this.attributes = {}; this.handlers = {};
    this.className = ''; this.textContent = ''; this.value = ''; this.checked = false;
    this.writes = 0;
    this.dataset = new Proxy({}, {set:(o, k, v) => { this.writes++; o[k] = v; return true; }});
    this.classList = {
      add: name => { const s = new Set(this.className.split(' ').filter(Boolean)); s.add(name); this.className = [...s].join(' '); },
      toggle:(name, on) => { const s = new Set(this.className.split(' ').filter(Boolean)); if (on) s.add(name); else s.delete(name); this.className = [...s].join(' '); },
      contains:name => this.className.split(' ').includes(name)
    };
  }
  append(...items) {
    for (const item of items.flatMap(item => item.tag === 'fragment' ? item.children : [item])) {
      if (item.parentElement) item.parentElement.children = item.parentElement.children.filter(child => child !== item);
      this.children.push(item); item.parentElement = this;
    }
  }
  setAttribute(k, v) { this.attributes[k] = v; }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  dispatch(type) { for (const fn of this.handlers[type] || []) fn({target:this}); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) {
    return this.children.flatMap(c => [
      ...(selector.startsWith('.') ? c.classList.contains(selector.slice(1)) : c.tag === selector) ? [c] : [],
      ...c.querySelectorAll(selector)
    ]);
  }
}
function setup({stored = null, reduced = false, storageThrows = false} = {}) {
  let now = 1000, seq = 0, observerCallback;
  const frames = new Map(), draws = [], buffers = [], writes = [];
  const root = new Element();
  for (let i = 0; i < 3; i++) {
    const tile = new Element(); tile.className = 'live-tile';
    const portrait = new Element(); portrait.className = 'hud-portrait';
    tile.append(portrait); root.append(tile);
  }
  const cards = new Element(); cards.className = 'right-column';
  for (let i = 0; i < 3; i++) {
    const card = new Element('article'); card.className = 'card';
    const head = new Element(); head.className = 'cardhead';
    const number = new Element(); number.className = 'number'; head.append(number);
    const slot = new Element(); slot.className = 'emotion-slot';
    card.append(head, slot); cards.append(card);
  }
  const elements = {cards, liveAvatars:root};
  const document = new Element('document'); document.readyState = 'complete'; document.hidden = false;
  document.getElementById = id => elements[id] || null;
  document.querySelectorAll = selector => selector === '.right-column > article.card' ? cards.children : [];
  document.createElement = tag => new Element(tag);
  document.createDocumentFragment = () => new Element('fragment');
  const media = new Element(); media.matches = reduced;
  const ctx = vm.createContext({
    document, console, performance:{now:() => now},
    localStorage:{getItem:() => { if (storageThrows) throw Error('blocked'); return stored; }, setItem:(k, v) => { if (storageThrows) throw Error('blocked'); writes.push([k, JSON.parse(v)]); }},
    requestAnimationFrame:fn => { frames.set(++seq, fn); return seq; }, cancelAnimationFrame:id => frames.delete(id),
    YapPixelEngine:{...engine, draw:(id, pose, meta) => { draws.push({id, pose, meta}); return engine.draw(id, pose, meta); }},
    matchMedia:() => media,
    IntersectionObserver:class { constructor(fn) { observerCallback = fn; } observe() {} }
  });
  ctx.window = ctx;
  vm.runInContext(`const speech = {audibleAgent:null, audibleEntry:null, audioMeter:null};
    const state = {current:null, paused:false};
    const defs = [{name:'Норман'}, {name:'Глитч'}, {name:'Джесси'}];`, ctx);
  vm.runInContext(adapter, ctx);
  const speech = vm.runInContext('speech', ctx), state = vm.runInContext('state', ctx);
  return {ctx, root, cards, document, speech, state, frames, draws, buffers, writes, media,
    api:ctx.YapdOmePixel,
    tick(ms = 100) { now += ms; const pending = [...frames.values()]; frames.clear(); for (const fn of pending) fn(now); },
    offscreen(on) { observerCallback([{isIntersecting:!on}]); },
    meter(value) { speech.audioMeter = {fftSize:128, getFloatTimeDomainData(a) { buffers.push(a); a.fill(value); }}; },
    start(agent, text = 'обычная реплика', qwenEmotion, mode = 'local') {
      speech.audibleAgent = agent; speech.audibleEntry = {text, config:{qwenEmotion}, audioMode:mode}; ctx.YapdOmePixel.sync();
    },
    lastDraw(id) { return draws.filter(d => d.id === id).at(-1); }
  };
}

test('mounts exactly 3×2304 DOM LEDs, no fallback SVGs, default 12fps and diff-only writes', () => {
  const h = setup();
  assert.equal(h.root.querySelectorAll('.pixel-led').length, 6912);
  assert.equal(h.root.querySelectorAll('svg').length, 0);
  assert.equal(h.root.querySelectorAll('.pixel-controls').length, 0);
  assert.equal(h.cards.querySelectorAll('.pixel-mood').length, 3);
  assert.equal(h.cards.querySelectorAll('.entity-avatar-select').length, 3);
  for (const select of h.cards.querySelectorAll('.entity-avatar-select')) assert.equal(select.children.length, 3);
  for (const select of h.cards.querySelectorAll('.pixel-mood')) assert.equal(select.children.length, 11);
  assert.equal(h.api.getStatus().fps, 12);
  assert.equal(h.api.getStatus().agents.map(a => a.avatarId).join(','), 'norman,glitch,jessie');
  const avatarSelects = h.cards.querySelectorAll('.entity-avatar-select');
  avatarSelects[0].value = 'jessie'; avatarSelects[0].dispatch('change');
  assert.equal(h.api.getStatus().agents[0].avatarId, 'jessie');
  assert.equal(h.root.querySelectorAll('.pixel-grid')[0].dataset.avatar, 'jessie');
  assert.equal(h.root.querySelectorAll('.live-tile')[0].dataset.avatar, 'jessie');
  assert.equal(h.cards.querySelectorAll('.entity-avatar-select')[0].value, 'jessie');
  assert.equal(h.writes.at(-1)[1].avatars[0], 'jessie');
  const restored = setup({stored:JSON.stringify(h.writes.at(-1)[1])});
  assert.equal(restored.api.getStatus().agents[0].avatarId, 'jessie');
  assert.equal(h.cards.querySelectorAll('.pixel-fps').length, 3);
  for (const select of h.cards.querySelectorAll('.pixel-fps')) assert.equal(select.value, '12');
  assert.equal(h.document.getElementById('pixelPuppetEnabled'), null);

  const leds = h.root.querySelectorAll('.pixel-led');
  const before = leds.reduce((n, led) => n + led.writes, 0);
  h.api.sync(); h.api.boot();
  assert.equal(leds.reduce((n, led) => n + led.writes, 0), before);
  assert.equal(h.root.querySelectorAll('.pixel-led').length, 6912);
  h.tick(1); const count = h.draws.length; h.tick(10);
  assert.equal(h.draws.length, count, 'render capped below 12fps');
});

test('actual audible owner only; RMS buffer reused; true silence and STOP immediately close all mouths', () => {
  const h = setup(); h.state.current = {agent:2}; h.api.sync();
  assert.equal(h.api.getStatus().agents[2].mood, 'focus');
  assert.equal(h.api.getStatus().agents.filter(a => a.speaking).length, 0);
  h.meter(.2); h.start(0, 'Ого!!', 'dramatic');
  assert.ok(Math.abs(h.api.getStatus().agents[0].level - .8) < .001);
  assert.equal(h.api.getStatus().agents[0].mood, 'surprise');
  h.tick(); h.tick(); assert.equal(h.buffers[0], h.buffers.at(-1));
  assert.ok(h.lastDraw('glitch').pose.gaze < 0);
  assert.equal(h.api.getStatus().agents[2].level, 0);
  h.speech.audioMeter.getFloatTimeDomainData = a => a.fill(0); h.api.sync();
  assert.equal(h.api.getStatus().agents[0].level, 0);
  assert.equal(h.lastDraw('norman').pose.open, 0); assert.equal(h.lastDraw('norman').pose.round, 0);
  h.speech.audioMeter.getFloatTimeDomainData = a => a.fill(.25); h.api.sync();
  assert.equal(h.lastDraw('norman').meta.talk, 1);
  h.speech.audibleAgent = null; h.speech.audibleEntry = null; h.api.sync();
  for (const a of h.api.getStatus().agents) assert.equal(a.level, 0);
  assert.equal(h.lastDraw('norman').meta.talk, 0);
  assert.equal(h.lastDraw('norman').pose.open, 0); assert.equal(h.lastDraw('norman').pose.round, 0);
});

test('browser envelope starts only with actual speech; qwen snapshot and bounded text heuristics', () => {
  const h = setup();
  h.speech.audibleEntry = {audioMode:'browser', text:'Ура!', config:{qwenEmotion:'excited'}};
  h.api.sync(); assert.equal(h.api.getStatus().agents[0].level, 0);
  h.start(1, 'Ура!', 'calm', 'browser');
  assert.ok(h.api.getStatus().agents[1].level > 0);

  assert.equal(h.api.getStatus().agents[1].mood, 'neutral');
  h.speech.audibleEntry.config.qwenEmotion = 'dramatic'; h.api.sync();
  assert.equal(h.api.getStatus().agents[1].mood, 'neutral', 'config snapshotted on actual start');
  h.start(1, 'Ура!', 'excited', 'browser'); assert.equal(h.api.getStatus().agents[1].mood, 'joy');
  h.start(1, 'Ого!!', 'excited', 'browser'); assert.equal(h.api.getStatus().agents[1].mood, 'surprise');
  h.start(1, 'Много нового', 'excited', 'browser'); assert.equal(h.api.getStatus().agents[1].mood, 'joy');
  h.start(2, 'Ура!', 'neutral'); assert.equal(h.api.getStatus().agents[2].mood, 'joy');
  h.start(2, 'Температура и много нового', 'neutral'); assert.equal(h.api.getStatus().agents[2].mood, 'neutral');
  h.start(2, 'Мне грустно'); assert.equal(h.api.getStatus().agents[2].mood, 'sad');
  assert.match(h.api.getStatus().agents[2].source, /эвристика/);
  h.start(2, 'x'.repeat(2048) + ' грустно'); assert.equal(h.api.getStatus().agents[2].mood, 'neutral');
  assert.equal(h.api.getStatus().agents[2].level, 0, 'no analyser never invents local speech level');
});

test('manual mood priority; strict temporary events cannot control actual speech', () => {
  const h = setup(); h.start(0, '', 'calm', 'browser');
  const select = h.cards.querySelectorAll('.pixel-mood')[0]; select.value = 'angry'; select.dispatch('change');
  assert.equal(h.api.receive({type:'reaction', agent:0, emotion:'joy', duration:100}), true);
  assert.equal(h.api.getStatus().agents[0].mood, 'angry');
  select.value = 'auto'; select.dispatch('change'); assert.equal(h.api.getStatus().agents[0].mood, 'joy');
  h.tick(200); assert.equal(h.api.getStatus().agents[0].mood, 'neutral');
  for (const evt of [null, {type:'speech_start', agent:2}, {type:'audio_level', agent:2, level:1},
    {type:'reaction', agent:3, emotion:'joy'}, {type:'reaction', agent:0, emotion:'__proto__'},
    {type:'gaze', agent:1, direction:NaN}, {type:'gaze', agent:1, direction:2},
    {type:'reaction', agent:0, emotion:'joy', duration:Infinity},
    {type:'reaction', agent:0, emotion:'joy', speaking:true}]) assert.equal(h.api.receive(evt), false);
  assert.equal(h.api.receive({type:'gaze', agent:'jessie', direction:-1}), true);
  assert.equal(h.speech.audibleAgent, 0); assert.equal(h.api.getStatus().speaker, 0);
  assert.equal(h.api.getStatus().agents[2].level, 0);
  vm.runInContext("defs[0].name = 'Новое имя'", h.ctx); h.api.sync();
  assert.equal(h.root.querySelectorAll('.pixel-grid')[0].attributes['aria-label'], 'Новое имя: Спокойствие');
});

test('animation stays enabled; hidden and offscreen pause rendering, reduced motion remains accessible', () => {
  const h = setup(); h.start(0, '', 'dramatic', 'browser');
  assert.equal(h.document.getElementById('pixelPuppetEnabled'), null);
  assert.equal(h.frames.size, 1);
  h.document.hidden = true; h.document.dispatch('visibilitychange'); assert.equal(h.frames.size, 0);
  h.speech.audibleAgent = null; h.speech.audibleEntry = null; h.api.sync();
  assert.equal(h.api.getStatus().agents[0].level, 0);
  h.document.hidden = false; h.document.dispatch('visibilitychange'); assert.equal(h.frames.size, 1);
  h.offscreen(true); assert.equal(h.frames.size, 0); h.offscreen(false); assert.equal(h.frames.size, 1);
  const r = setup({reduced:true}); assert.equal(r.frames.size, 0);
  r.start(0, '', 'calm', 'browser'); assert.equal(r.frames.size, 1);
  assert.equal(r.lastDraw('norman').meta.t, 0); assert.equal(r.lastDraw('norman').meta.blink, 0);
  r.speech.audibleAgent = null; r.api.sync(); assert.equal(r.frames.size, 0);
});

test('isolated storage: corrupt/invalid/blocked values safe; valid settings restored and persisted', () => {
  for (const stored of ['{broken', 'null', '[]', '{"enabled":"false","fps":1000,"moods":["__proto__",null,7]}']) {
    const h = setup({stored}); assert.equal(h.api.getStatus().fps, 12);
    assert.equal(h.cards.querySelectorAll('.pixel-mood')[0].value, 'auto');
  }
  const h = setup({stored:'{"enabled":false,"fps":20,"moods":["joy","auto","focus"]}'});
  assert.equal(h.api.getStatus().fps, 20);
  assert.equal(h.frames.size, 1); assert.equal(h.api.getStatus().agents[0].mood, 'joy');
  const fps = h.cards.querySelectorAll('.pixel-fps');
  fps[0].value = '30'; fps[0].dispatch('change');
  assert.equal(h.writes.at(-1)[0], h.api.storageKey); assert.equal(h.writes.at(-1)[1].fps, 30);
  assert.ok(fps.every(select => select.value === '30'), 'FPS selectors stay synchronized');
  fps[0].value = '120'; fps[0].dispatch('change'); assert.equal(h.api.getStatus().fps, 30);
  const blocked = setup({storageThrows:true});
  assert.equal(blocked.api.getStatus().fps, 12);
});
