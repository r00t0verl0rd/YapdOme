'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const client=fs.readFileSync(path.join(__dirname,'../frontend/client.js'),'utf8');
const hud=fs.readFileSync(path.join(__dirname,'../frontend/animation/hud-reference.css'),'utf8');

test('chat transcript shows speaker and spoken text without engine metadata',()=>{
  const start=client.indexOf('function transcriptLine(el){');
  const end=client.indexOf('}',start);
  assert.ok(start>=0&&end>start);
  const transcript=client.slice(start,end+1);
  assert.ok(transcript.includes("querySelector('.who').textContent+': '+el.querySelector('.body').textContent"));
  assert.ok(!transcript.includes("querySelector('.meta')"));
  assert.ok(hud.includes('.feed .message .meta{display:none!important}'));
  assert.ok(hud.includes('.feed .message .body{'));
});

test('chat start and normal stop do not add system bookkeeping rows',()=>{
  assert.ok(!client.includes("system('Тема (приоритет): "));
  assert.ok(!client.includes("system('Диалог остановлен ведущим.')"));
  assert.ok(client.includes("$('stop').onclick=stopDialogue;"));
});

test('stock personas have distinct speaking styles and existing custom profiles are preserved',()=>{
  const start=client.indexOf('const defs = [');
  const end=client.indexOf('];',start)+2;
  const defs=client.slice(start,end);
  assert.ok(defs.includes('самоиронией'));
  assert.ok(defs.includes('сарказм и словесные дуэли'));
  assert.ok(defs.includes('сухой юмор и неожиданный поворот'));
  assert.ok(client.includes('if(a.description===previousDefaults[i])d.description=upgradedDefaults[i]'));
  assert.ok(client.includes('else if(a.description!==obsolete[i])d.description=a.description.slice(0,900)'));
});
