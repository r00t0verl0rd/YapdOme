"""Kokoro RU local sidecar; weights by zaakirio/kokoro-ru (OpenRAIL)."""
import io, json, sys, threading, wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
VOICES=("sveta","masha","dima")
def worker(root,port):
 import torch,numpy as np
 from kokoro import KModel
 sys.path.insert(0,str(root))
 from ru_g2p import RuG2P
 g2p=RuG2P();models={};packs={}
 # Prepare the common female checkpoint once. The male checkpoint is lazy:
 # loading both immediately doubled cold-start time and RAM usage.
 for voice in VOICES:
  packs[voice]=torch.load(root/"voices"/(voice+".pt"),map_location="cpu",weights_only=False)
 models["kokoro-ru-v2-base.pth"]=KModel(
     repo_id="zaakirio/kokoro-ru",
     model=str(root/"kokoro-ru-v2-base.pth")).eval()
 # Warm one real Russian phrase so readiness reflects working inference.
 ipa_probe, oov_probe = g2p("Привет.")
 if not ipa_probe or oov_probe:raise RuntimeError("Kokoro RU phonetic initialization failed")
 with torch.inference_mode():
  models["kokoro-ru-v2-base.pth"](
      ipa_probe,packs["sveta"][len(ipa_probe)-1],1.0,return_output=True).audio
 model_lock=threading.RLock()
 def voice_model(name):
  with model_lock:
   if name not in models:
    models[name]=KModel(repo_id="zaakirio/kokoro-ru",model=str(root/name)).eval()
   return models[name]
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*_):pass
  def send(self,status,content,typ):
   self.send_response(status);self.send_header("Content-Type",typ);self.send_header("Content-Length",str(len(content)));self.end_headers();self.wfile.write(content)
  def do_GET(self):
   if self.path=="/health":self.send(200,b'{"status":"ok"}',"application/json")
   else:self.send_error(404)
  def do_POST(self):
   if self.path!="/speak":self.send_error(404);return
   try:
    size=int(self.headers.get("Content-Length","0"))
    if not 0<size<=4096:raise ValueError("Размер запроса")
    d=json.loads(self.rfile.read(size));voice=d["voice"];speed=d["speed"];text=d["text"]
    if voice not in VOICES or not isinstance(text,str) or not 0<len(text)<=450 or type(speed) not in (int,float) or not .75<=speed<=1.5:raise ValueError("Параметры")
    ipa,oov=g2p(text)
    if oov or not 0<len(ipa)<=500:raise ValueError("Русская фонетика не распознана")
    name="kokoro-ru-v2-dima.pth" if voice=="dima" else "kokoro-ru-v2-base.pth"
    model=voice_model(name)
    with torch.inference_mode():audio=model(ipa,packs[voice][len(ipa)-1],speed,return_output=True).audio
    pcm=(np.clip(audio.cpu().numpy(),-1,1)*32767).astype("<i2")
    out=io.BytesIO()
    with wave.open(out,"wb") as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(pcm.tobytes())
    self.send(200,out.getvalue(),"audio/wav")
   except (ValueError,KeyError,TypeError,IndexError) as e:self.send(400,json.dumps({"error":str(e)}).encode(),"application/json")
   except Exception:
    import traceback
    traceback.print_exc()
    self.send(503,b'{"error":"Russian inference failed; see worker.log"}',"application/json")
 ThreadingHTTPServer(("127.0.0.1",port),Handler).serve_forever()
if __name__=="__main__" and len(sys.argv)==4 and sys.argv[1]=="--worker":worker(Path(sys.argv[2]),int(sys.argv[3]))
