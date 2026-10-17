'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const code=fs.readFileSync(path.join(__dirname,'../frontend/client.js'),'utf8');
const html=fs.readFileSync(path.join(__dirname,'../frontend/index.html'),'utf8');
const styles=fs.readFileSync(path.join(__dirname,'../frontend/style.css'),'utf8');
const section=(start,end)=>{
 const first=code.indexOf(start),last=code.indexOf(end,first+start.length);
 assert.ok(first>=0&&last>first,'Missing JS section: '+start);
 return code.slice(first,last);
};
// The dropdown exposes one kokoro entry; internally there are two kokoro addons
// (English INT8 and Russian) plus the other local engines.
const dropdown=['piper','silero','kokoro','qwen3-tts','openaudio-s1-mini','browser'];
const addons=[
 {key:'kokoro-ru',id:'kokoroRu'},
 {key:'kokoro',id:'kokoro'},
 {key:'piper',id:'piper'},
 {key:'silero',id:'silero'},
 {key:'qwen3-tts',id:'qwen3'},
 {key:'openaudio-s1-mini',id:'openaudio'}
];
const effectiveFor=key=>key==='kokoro'?'kokoro-ru':key;
function harness(){
 const ids=['ttsBackend','voiceHint','cards','browserInstaller','kokoroModelWrap'];
 for(const engine of addons)ids.push(engine.id+'Installer');
 const nodes=Object.fromEntries(ids.map(id=>[id,{hidden:true,value:'',textContent:''}]));
 nodes.ttsBackend.value='piper';
 const defs=[
  {name:'Норман',voiceURI:'',piperVoice:'dmitri',sileroVoice:'aidar'},
  {name:'Глитч',voiceURI:'',piperVoice:'irina',sileroVoice:'baya'},
  {name:'Джесси',voiceURI:'',piperVoice:'ruslan',sileroVoice:'kseniya'}
 ];
 const activation=[],warmups=[],save=[],cardRenders=[];
 const context={
  $:id=>nodes[id],defs,kokoroModel:'ru',
  addons:addons.map(x=>({...x})),
  engineHints:{piper:'Piper',silero:'Silero',kokoro:'Kokoro','qwen3-tts':'Qwen3','openaudio-s1-mini':'OpenAudio',browser:'macOS'},
  activateVoiceEngine:key=>activation.push(key),
  warmPiperVoice:voice=>warmups.push(voice),piperState:{ready:true},
  savePrefs:()=>save.push(1),forceRenderCards:()=>cardRenders.push(1)
 };
 vm.createContext(context);
 vm.runInContext(section('function setAgentVoice(agent,voice){','function renderAddonStatus(addon,data){'),context);
 const assignment=code.split('\n').find(line=>line.trimStart().startsWith("$('ttsBackend').onchange="));
 assert.ok(assignment,'Voice selector handler must exist');
 vm.runInContext(assignment,context);
 return {nodes,defs,context,activation,warmups,save,cardRenders};
}
test('switching TTS exposes only the selected technical panel',()=>{
 const h=harness();
 for(const key of dropdown){
  h.nodes.ttsBackend.value=key;
  assert.doesNotThrow(()=>h.nodes.ttsBackend.onchange(),key);
  const effective=effectiveFor(key);
  for(const addon of addons){
   assert.equal(h.nodes[addon.id+'Installer'].hidden,addon.key!==effective,
    key+' must show only the active panel');
  }
  assert.equal(h.nodes.browserInstaller.hidden,key!=='browser');
  assert.equal(h.nodes.kokoroModelWrap.hidden,key!=='kokoro');
  assert.equal(h.nodes.voiceHint.textContent,h.context.engineHints[key]);
 }
 assert.deepEqual(h.activation.map(String),dropdown.map(effectiveFor));
 assert.equal(h.cardRenders.length,dropdown.length);
 assert.equal(h.save.length,dropdown.length);
});
test('voice selection stays in character cards and persists separately per engine',()=>{
 const h=harness();
 h.context.setAgentVoice(0,'denis');
 assert.equal(h.defs[0].piperVoice,'denis');
 assert.deepEqual(h.warmups,['denis']);
 h.nodes.ttsBackend.value='silero';h.nodes.ttsBackend.onchange();
 h.context.setAgentVoice(0,'eugene');
 assert.equal(h.defs[0].sileroVoice,'eugene');
 h.nodes.ttsBackend.value='openaudio-s1-mini';h.nodes.ttsBackend.onchange();
 h.context.setAgentVoice(0,'voice-2');
 assert.equal(h.defs[0].openaudioVoice,'voice-2');
 h.nodes.ttsBackend.value='piper';h.nodes.ttsBackend.onchange();
 assert.equal(h.defs[0].piperVoice,'denis');
 assert.match(code,/select\.onchange=\(\)=>setAgentVoice\(i,select\.value\)/);
 assert.doesNotMatch(html,/voiceAgent(?:Settings|Label|[0-9])/);
 assert.doesNotMatch(styles,/\.voice-agent-(?:settings|row)/);
 assert.doesNotMatch(code,/updatePanelAgentVoices|voiceAgent[0-9]/);
});
test('all local TTS retain their status, paths, install and worker controls',()=>{
 for(const engine of addons){
  const prefix=engine.id;
  assert.match(html,new RegExp('id="'+prefix+'Installer"'));
  for(const suffix of ['Status','Directory','Browse','Install','Cancel','Restart','Progress','ProgressLabel','ProgressFile','ProgressPercent','Error']){
   assert.match(html,new RegExp('id="'+prefix+suffix+'"'),engine.key+': missing '+suffix);
  }
 }
 assert.match(html,/Путь к модели не требуется/);
 assert.doesNotMatch(code,/updateTTSUI\s*\(/,'removed Qwen updater cannot break selection');
});
