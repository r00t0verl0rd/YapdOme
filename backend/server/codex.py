"""Local Codex App Server JSON-RPC client (stdio transport)."""
import json
import shutil
import subprocess
import threading


class CodexError(RuntimeError):
    pass


class CodexAppServer:
    def __init__(self):
        self.lock = threading.RLock()
        self.start_lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.pending = {}
        self.listeners = []
        self.next_id = 0
        self.process = None
        self.account = None
        self.login_result = None
        self.error = ""

    def _start(self):
        with self.start_lock:
            if self.process and self.process.poll() is None:
                return
            executable = shutil.which("codex")
            if not executable:
                raise CodexError("Codex CLI не найден. Установи Codex CLI и перезапусти YapdOme.")
            self.process = subprocess.Popen([executable, "app-server", "--listen", "stdio://"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", bufsize=1)
            threading.Thread(target=self._reader, daemon=True).start()
            self._request("initialize", {"clientInfo":{"name":"yapdome","title":"YapdOme","version":"0.2"}}, timeout=20)
            self._notify("initialized", {})

    def _reader(self):
        process = self.process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                try: msg = json.loads(line)
                except ValueError: continue
                if "id" in msg:
                    with self.lock:
                        waiter = self.pending.get(msg["id"])
                    if waiter: waiter["response"] = msg; waiter["event"].set()
                else:
                    for listener in list(self.listeners):
                        try: listener(msg)
                        except Exception: pass
        except (OSError, ValueError):
            pass
        self.error = "Соединение с Codex App Server завершено"
        with self.lock:
            for item in self.pending.values():
                item["response"] = {"error":{"message":self.error}}; item["event"].set()

    def _notify(self, method, params):
        self._start()
        process = self.process
        if process is None or process.stdin is None:
            raise CodexError("Codex App Server не запущен")
        with self.write_lock:
            process.stdin.write(json.dumps({"method":method,"params":params})+"\n")
            process.stdin.flush()

    def _request(self, method, params=None, timeout=30):
        self._start()
        with self.lock:
            self.next_id += 1; ident = self.next_id
            waiter = {"event":threading.Event(),"response":None}
            self.pending[ident] = waiter
        self._start_write({"method":method,"id":ident,"params":params or {}})
        if not waiter["event"].wait(timeout):
            with self.lock: self.pending.pop(ident, None)
            raise CodexError("Тайм-аут Codex App Server: "+method)
        with self.lock: self.pending.pop(ident, None)
        response = waiter["response"] or {}
        if "error" in response: raise CodexError(response["error"].get("message", "Ошибка Codex"))
        return response.get("result", {})

    def _start_write(self, message):
        process = self.process
        if process is None or process.stdin is None:
            raise CodexError("Codex App Server не запущен")
        with self.write_lock:
            process.stdin.write(json.dumps(message)+"\n")
            process.stdin.flush()

    def status(self):
        with self.lock:
            account = self.account
        try:
            result = self._request("account/read", {"refreshToken":False}, timeout=10)
            account = result.get("account")
            with self.lock:
                self.account = account
                self.error = ""
        except (CodexError, OSError, AttributeError) as exc:
            self.error = str(exc) or "Не удалось запустить Codex App Server"
        return {"codex_connected":bool(account and account.get("type")=="chatgpt"),
                "codex_account":(account or {}).get("email"),"codex_error":self.error}

    def login(self):
        result = self._request("account/login/start", {"type":"chatgpt","useHostedLoginSuccessPage":True,"appBrand":"codex"})
        return {"url":result.get("authUrl")}

    def models(self):
        result = self._request("model/list", {"limit":100,"includeHidden":False})
        return [{"slug":m.get("id"),"name":m.get("displayName") or m.get("id")}
                for m in result.get("data",[]) if isinstance(m.get("id"),str) and not m.get("hidden")]

    def generate(self, model, instructions, messages, cancelled, emit):
        self._start()
        thread = self._request("thread/start", {"model":model,"approvalPolicy":"never","sandbox":"read-only"}, timeout=30).get("thread",{})
        thread_id = thread.get("id")
        if not thread_id: raise CodexError("Codex не вернул thread id")
        done = threading.Event(); failure = []
        def on_event(msg):
            params=msg.get("params") or {}
            if params.get("threadId") != thread_id: return
            if msg.get("method")=="item/agentMessage/delta": emit("delta",params.get("delta", ""))
            elif msg.get("method")=="turn/completed":
                turn=params.get("turn",{}); status=turn.get("status")
                if status=="failed": failure.append((turn.get("error") or {}).get("message","Codex generation failed"))
                done.set()
        self.listeners.append(on_event)
        try:
            prompt="YapdOme is a dialogue generator. Do not use tools, run commands, or modify files. Reply only with the requested spoken dialogue.\n\n"+instructions+"\n\nConversation context:\n"+"\n".join(str(m.get("content", "")) for m in messages)
            self._request("turn/start", {"threadId":thread_id,"input":[{"type":"text","text":prompt}],"model":model,
                "approvalPolicy":"never","sandboxPolicy":{"type":"readOnly","access":{"type":"fullAccess"}}}, timeout=30)
            while not done.wait(.1):
                if cancelled.is_set():
                    try: self._request("turn/interrupt",{"threadId":thread_id},timeout=5)
                    except CodexError: pass
                    return
            if failure: raise CodexError(failure[0])
        finally:
            if on_event in self.listeners: self.listeners.remove(on_event)


CODEX = CodexAppServer()
