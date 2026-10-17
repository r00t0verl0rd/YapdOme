"""Local Kokoro 82M INT8 ONNX sidecar, no dependencies in the TRIAD process."""
import io
import json
import sys
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODEL = "kokoro-v1.0.int8.onnx"
VOICES_FILE = "voices-v1.0.bin"
VOICES = ("af_heart","af_bella","af_sarah","af_nicole","af_sky","am_adam","am_michael",
          "am_echo","am_puck","bf_emma","bf_isabella","bm_george","bm_lewis")
LANGS = ("en-us","en-gb")


def worker(root,port):
    from kokoro_onnx import Kokoro
    import numpy as np
    model=Kokoro(str(root/MODEL),str(root/VOICES_FILE))
    # Report ready only after a real inference succeeds; keep model resident.
    model.create("Hello.",voice="af_heart",lang="en-us")
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_): pass
        def reply(self,code,payload,typ):
            self.send_response(code)
            self.send_header("Content-Type",typ)
            self.send_header("Content-Length",str(len(payload)))
            self.end_headers();self.wfile.write(payload)
        def do_GET(self):
            if self.path=="/health": self.reply(200,b'{"status":"ok"}',"application/json")
            else: self.send_error(404)
        def do_POST(self):
            if self.path!="/speak": self.send_error(404);return
            try:
                size=int(self.headers.get("Content-Length","0"))
                if not 0<size<=4096: raise ValueError("Invalid request size")
                p=json.loads(self.rfile.read(size))
                voice=p.get("voice","af_heart");text=p.get("text","")
                speed=p.get("speed",1.0);lang=p.get("lang","en-us")
                if voice not in VOICES or lang not in LANGS: raise ValueError("Unknown voice or language")
                if not isinstance(text,str) or not 0<len(text)<=600: raise ValueError("Invalid text")
                if type(speed) not in (int,float) or not .65<=speed<=1.7: raise ValueError("Invalid speed")
                audio,rate=model.create(text,voice=voice,lang=lang,speed=float(speed))
                pcm=(np.clip(audio,-1,1)*32767).astype("<i2")
                f=io.BytesIO()
                with wave.open(f,"wb") as w:
                    w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(pcm.tobytes())
                self.reply(200,f.getvalue(),"audio/wav")
            except (TypeError,ValueError) as exc:
                self.reply(400,json.dumps({"error":str(exc)}).encode(),"application/json")
            except Exception:
                import traceback
                traceback.print_exc()
                self.reply(503,b'{"error":"Kokoro synthesis error; see worker.log"}',"application/json")
    ThreadingHTTPServer(("127.0.0.1",port),Handler).serve_forever()



if __name__=="__main__" and len(sys.argv)==4 and sys.argv[1]=="--worker":
    worker(Path(sys.argv[2]),int(sys.argv[3]))
