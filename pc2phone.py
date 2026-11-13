#!/usr/bin/env python3
"""pc2phone: stream this PC's audio to a phone browser over Wi-Fi, no virtual cable.

    pip install pyaudiowpatch aiohttp qrcode numpy
    py -3 pc2phone.py            window with a Start/Stop button and the QR code
    py -3 pc2phone.py --cli      same thing in the terminal
    py -3 pc2phone.py --firewall allow the port on Private networks (asks for admin)
"""
import argparse
import asyncio
import base64
import concurrent.futures
import json
import os
import secrets
import socket
import struct
import sys
import threading
import time

import numpy as np
import pyaudiowpatch as pyaudio
import qrcode
from aiohttp import web

DEFAULTS = {"latency": 80, "port": 8765}
LATENCIES = {"Low (40 ms)": 40, "Normal (80 ms)": 80, "Safe (160 ms)": 160}

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>PC audio</title>
<style>
 body{margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:18px;font:16px -apple-system,system-ui,sans-serif;background:#111;color:#eee}
 button{font:600 22px inherit;padding:22px 54px;border:0;border-radius:18px;background:#2d7ff9;color:#fff}
 button.on{background:#444}
 #st{font-size:18px;text-align:center;padding:0 16px} #info{font-size:13px;color:#999;font-variant-numeric:tabular-nums}
 select{font-size:15px;padding:6px;border-radius:8px}
</style></head><body>
<button id="b">Start</button>
<div id="st">Tap Start</div>
<div id="info"></div>
<label>Latency <select id="buf"><option value="40">low (40 ms)</option>
 <option value="80">normal (80 ms)</option><option value="160">safe (160 ms)</option></select></label>
<audio id="silent" loop playsinline src="__SILENT__"></audio>
<script>
const RATE=__RATE__, KEY="__KEY__";
const $=id=>document.getElementById(id);
let ctx=null, ws=null, on=false, next=0, drops=0, unders=0, lastMsg=0, lock=null;
let target=0.08;
$('buf').value="__BUF__";
function readBuf(){target=+$('buf').value/1000;}
$('buf').onchange=readBuf; readBuf();
const AC=window.AudioContext||window.webkitAudioContext;
const say=t=>$('st').textContent=t;

async function wake(){
  try{ if(on && navigator.wakeLock && !lock){ lock=await navigator.wakeLock.request('screen'); lock.onrelease=()=>lock=null; } }catch(e){}
}
function start(){
  try{ if(navigator.audioSession) navigator.audioSession.type='playback'; }catch(e){}
  $('silent').play().catch(()=>{});
  try{ ctx=new AC(RATE?{sampleRate:RATE,latencyHint:'interactive'}:{latencyHint:'interactive'}); }
  catch(e){ ctx=new AC(); }
  ctx.resume();
  on=true; next=0; $('b').textContent='Stop'; $('b').className='on';
  connect(); wake();
}
function stop(){
  on=false; if(ws) ws.close(); if(ctx) ctx.close(); ctx=null; $('silent').pause();
  if(lock) lock.release(); $('b').textContent='Start'; $('b').className=''; say('Stopped');
}
$('b').onclick=()=>on?stop():start();

function connect(){
  if(!on) return;
  say('Connecting…');
  ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws?k='+KEY);
  ws.binaryType='arraybuffer'; lastMsg=Date.now();
  ws.onopen=()=>{say('Playing'); next=0;};
  ws.onmessage=e=>{lastMsg=Date.now(); if(typeof e.data!=='string') play(e.data);};
  ws.onclose=()=>{ if(on){say('Reconnecting… (rescan the QR if the PC app was restarted)'); setTimeout(connect,1000);} };
  ws.onerror=()=>ws.close();
}
setInterval(()=>{ if(on && ws && ws.readyState===1 && Date.now()-lastMsg>4000) ws.close(); },1000);

function play(buf){
  if(!ctx) return;
  const rate=new DataView(buf).getUint32(0,true);
  const pcm=new Int16Array(buf,4), n=pcm.length>>1;
  const ab=ctx.createBuffer(2,n,rate), L=ab.getChannelData(0), R=ab.getChannelData(1);
  for(let i=0;i<n;i++){L[i]=pcm[2*i]/32768; R[i]=pcm[2*i+1]/32768;}
  const now=ctx.currentTime;
  if(next<now+0.005){ if(next>0) unders++; next=now+target; }
  else if(next-now>target+0.15){ drops++; return; }
  const s=ctx.createBufferSource(); s.buffer=ab; s.connect(ctx.destination); s.start(next);
  next+=ab.duration;
}
setInterval(()=>{ if(ctx) $('info').textContent='buffer '+Math.max(0,Math.round((next-ctx.currentTime)*1000))+' ms · dropped '+drops+' · underruns '+unders; },250);
document.addEventListener('visibilitychange',()=>{
  if(!document.hidden && on){ if(ctx&&ctx.state!=='running') ctx.resume(); $('silent').play().catch(()=>{});
    wake(); if(!ws||ws.readyState>1) connect(); }
});
document.addEventListener('touchend',()=>{ if(on&&ctx&&ctx.state!=='running') ctx.resume(); });
</script></body></html>"""


def silent_wav_uri():
    n = 4000
    hdr = b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 8000, 1, 8)
    wav = hdr + b"data" + struct.pack("<I", n) + b"\x80" * n
    return "data:audio/wav;base64," + base64.b64encode(wav).decode()


def mix_matrix(ch):
    m = np.zeros((ch, 2), np.float32)
    m[0, 0] = m[1, 1] = 1.0
    c = 0.707
    if ch == 4:
        m[2, 0] = m[3, 1] = c
    elif ch >= 3:
        m[2, :] = c
        if ch == 5:
            m[3, 0] = m[4, 1] = c
        if ch >= 6:
            m[4, 0] = m[5, 1] = c
        if ch >= 8:
            m[6, 0] = m[7, 1] = c
        for k in range(8, ch):
            m[k, k % 2] = c
    return m / m.sum(axis=0).max()


def to_stereo(data, ch, mix):
    a = np.frombuffer(data, np.int16)
    if ch == 2:
        return a.tobytes()
    a = a.reshape(-1, ch)
    if ch == 1:
        return np.repeat(a, 2, axis=1).tobytes()
    return np.clip(a.astype(np.float32) @ mix, -32768, 32767).astype(np.int16).tobytes()


def default_loopback():
    p = pyaudio.PyAudio()
    try:
        return p.get_default_wasapi_loopback()
    except (OSError, LookupError):
        return None
    finally:
        p.terminate()


def capture_thread(loop, hub, chunk_ms, stop, log):
    last_err = None
    while not stop.is_set():
        p = pyaudio.PyAudio()
        stream = None
        try:
            dev = p.get_default_wasapi_loopback()
            rate, ch = int(dev["defaultSampleRate"]), int(dev["maxInputChannels"])
            mix = mix_matrix(ch) if ch > 2 else None

            def cb(data, frames, t, status):
                loop.call_soon_threadsafe(hub.push, rate, to_stereo(data, ch, mix))
                return (None, pyaudio.paContinue)

            stream = p.open(format=pyaudio.paInt16, channels=ch, rate=rate, input=True,
                            input_device_index=dev["index"], frames_per_buffer=rate * chunk_ms // 1000,
                            stream_callback=cb)
            hub.rate = rate
            hub.device = dev["name"].replace(" [Loopback]", "")
            log(f"Capturing: {hub.device} ({rate} Hz, {ch} ch)")
            last_err = None
            while not stop.wait(2):
                if not stream.is_active():
                    raise RuntimeError("capture stream stopped")
                now = default_loopback()
                if now is None or now["name"] != dev["name"]:
                    log("Default output device changed, switching...")
                    break
        except Exception as e:
            hub.device = ""
            msg = f"{type(e).__name__}: {e}"
            if msg != last_err:
                log(f"Capture problem ({msg}); retrying...")
                last_err = msg
            stop.wait(2)
        finally:
            try:
                if stream:
                    stream.close()
            except Exception:
                pass
            p.terminate()
    hub.device = ""


class Hub:
    def __init__(self):
        self.clients = set()
        self.sockets = set()
        self.rate = 0
        self.device = ""
        self.ever_connected = False

    def push(self, rate, pcm):
        msg = struct.pack("<I", rate) + pcm
        for q in self.clients:
            if q.full():
                q.get_nowait()
            q.put_nowait(msg)


async def send_loop(ws, q):
    while True:
        try:
            await ws.send_bytes(await asyncio.wait_for(q.get(), 1.0))
        except asyncio.TimeoutError:
            await ws.send_str("k")


def make_app(hub, key, buf, log):
    async def index(request):
        if request.query.get("k") != key:
            return web.Response(status=403, text="Scan the QR code shown in the PC app.")
        html = (PAGE.replace("__RATE__", str(hub.rate)).replace("__KEY__", key)
                .replace("__BUF__", str(buf)).replace("__SILENT__", silent_wav_uri()))
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def ws_handler(request):
        if request.query.get("k") != key:
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(heartbeat=5, compress=False)
        await ws.prepare(request)
        q = asyncio.Queue(maxsize=25)
        hub.clients.add(q)
        hub.sockets.add(ws)
        hub.ever_connected = True
        log(f"Phone connected: {request.remote} ({len(hub.clients)} listening)")
        sender = asyncio.create_task(send_loop(ws, q))
        try:
            async for _ in ws:
                pass
        finally:
            sender.cancel()
            hub.clients.discard(q)
            hub.sockets.discard(ws)
            log(f"Phone disconnected: {request.remote} ({len(hub.clients)} listening)")
        return ws

    async def close_sockets(app):
        for ws in list(hub.sockets):
            await ws.close(code=1001)

    app = web.Application()
    app.add_routes([web.get("/", index), web.get("/ws", ws_handler)])
    app.on_shutdown.append(close_sockets)
    return app


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Server:
    def __init__(self, port, latency, chunk_ms=20, log=lambda *a: None):
        self.port, self.latency, self.chunk_ms, self.log = port, latency, chunk_ms, log
        self.hub = Hub()
        self.key = secrets.token_urlsafe(6)
        self.url = f"http://{lan_ip()}:{port}/?k={self.key}"

    def start(self):
        self.loop = asyncio.new_event_loop()
        self.stop_event = threading.Event()
        ready = concurrent.futures.Future()

        def run():
            asyncio.set_event_loop(self.loop)

            async def up():
                self.runner = web.AppRunner(make_app(self.hub, self.key, self.latency, self.log), access_log=None)
                await self.runner.setup()
                await web.TCPSite(self.runner, "0.0.0.0", self.port).start()

            try:
                self.loop.run_until_complete(up())
            except Exception as e:
                ready.set_exception(e)
                self.loop.close()
                return
            ready.set_result(None)
            self.loop.run_forever()
            self.loop.close()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        ready.result()
        self.capture = threading.Thread(
            target=capture_thread, args=(self.loop, self.hub, self.chunk_ms, self.stop_event, self.log), daemon=True)
        self.capture.start()

    def stop(self):
        self.stop_event.set()
        self.capture.join(10)
        try:
            asyncio.run_coroutine_threadsafe(self.runner.cleanup(), self.loop).result(10)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(10)


def qr_matrix(url, border=2):
    qr = qrcode.QRCode(border=border)
    qr.add_data(url)
    return qr.get_matrix()


def print_qr(url):
    m = qr_matrix(url)
    if len(m) % 2:
        m.append([False] * len(m[0]))
    ch = {(1, 1): " ", (1, 0): "▄", (0, 1): "▀", (0, 0): "█"}
    print()
    for y in range(0, len(m), 2):
        print("  " + "".join(ch[(int(a), int(b))] for a, b in zip(m[y], m[y + 1])))
    print()


def add_firewall_rule(port):
    import ctypes
    cmd = (f'/c netsh advfirewall firewall delete rule name="pc2phone" >nul 2>&1 & '
           f'netsh advfirewall firewall add rule name="pc2phone" dir=in action=allow protocol=TCP '
           f'localport={port} profile=private & pause')
    ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", cmd, None, 1)


def config_path():
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "pc2phone", "config.json")


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(config_path(), encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(config_path()), exist_ok=True)
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except OSError:
        pass


def run_gui():
    import ctypes
    import tkinter as tk
    from tkinter import ttk

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    cfg = load_config()
    root = tk.Tk()
    root.title("PC to Phone")
    root.resizable(False, False)
    scale = root.winfo_fpixels("1i") / 96
    state = {"server": None}

    body = ttk.Frame(root, padding=16)
    body.pack()
    button = ttk.Button(body, text="Start", width=26)
    button.grid(row=0, column=0, columnspan=2, ipady=8, pady=(0, 12))

    ttk.Label(body, text="Latency").grid(row=1, column=0, sticky="w")
    names = list(LATENCIES)
    current = next((n for n, v in LATENCIES.items() if v == cfg["latency"]), names[1])
    latency_box = ttk.Combobox(body, values=names, state="readonly", width=16)
    latency_box.set(current)
    latency_box.grid(row=1, column=1, sticky="e", pady=2)

    ttk.Label(body, text="Port").grid(row=2, column=0, sticky="w")
    port_var = tk.StringVar(value=str(cfg["port"]))
    port_box = ttk.Spinbox(body, from_=1024, to=65535, textvariable=port_var, width=18)
    port_box.grid(row=2, column=1, sticky="e", pady=2)

    status = ttk.Label(body, text="Stopped", wraplength=int(260 * scale))
    status.grid(row=3, column=0, columnspan=2, pady=(12, 0))

    qr_frame = ttk.Frame(body)
    canvas = tk.Canvas(qr_frame, highlightthickness=0, bg="white")
    canvas.pack(pady=(12, 6))
    url_var = tk.StringVar()
    url_box = ttk.Entry(qr_frame, textvariable=url_var, state="readonly", width=34, justify="center")
    url_box.pack()
    ttk.Label(qr_frame, text="Scan with the phone camera (same Wi-Fi)").pack(pady=(6, 0))

    def draw_qr(url):
        m = qr_matrix(url)
        px = max(4, int(5 * scale))
        size = len(m) * px
        canvas.config(width=size, height=size)
        canvas.delete("all")
        for y, row in enumerate(m):
            for x, dark in enumerate(row):
                if dark:
                    canvas.create_rectangle(x * px, y * px, (x + 1) * px, (y + 1) * px, fill="black", outline="")

    def refresh():
        srv = state["server"]
        if srv is None:
            return
        if srv.hub.clients:
            n = len(srv.hub.clients)
            text = f"Streaming to {n} phone{'s' if n > 1 else ''}"
        else:
            text = "Waiting for the phone: scan the QR code"
        text += f"\n{srv.hub.device}" if srv.hub.device else "\nNo audio output device found"
        status.config(text=text)
        root.after(500, refresh)

    def set_controls(enabled):
        s = "readonly" if enabled else "disabled"
        latency_box.config(state=s)
        port_box.config(state="normal" if enabled else "disabled")

    def start():
        try:
            port = int(port_var.get())
            if not 1024 <= port <= 65535:
                raise ValueError
        except ValueError:
            status.config(text="Port must be a number between 1024 and 65535")
            return
        latency = LATENCIES[latency_box.get()]
        save_config({"latency": latency, "port": port})
        srv = Server(port, latency)
        try:
            srv.start()
        except OSError:
            status.config(text=f"Port {port} is in use. Pick another one.")
            return
        state["server"] = srv
        set_controls(False)
        button.config(text="Stop")
        url_var.set(srv.url)
        draw_qr(srv.url)
        qr_frame.grid(row=4, column=0, columnspan=2)
        root.geometry("")
        refresh()

    def stop():
        srv, state["server"] = state["server"], None
        if srv:
            srv.stop()
        qr_frame.grid_remove()
        set_controls(True)
        button.config(text="Start")
        status.config(text="Stopped")
        root.geometry("")

    def toggle():
        if state["server"] is None:
            start()
        else:
            stop()

    def close():
        if state["server"]:
            stop()
        root.destroy()

    button.config(command=toggle)
    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()


def run_cli(port, latency, chunk_ms):
    srv = Server(port, latency, chunk_ms, log=print)
    try:
        srv.start()
    except OSError as e:
        sys.exit(f"Can't listen on port {port} ({e}). Try --port 8766.")
    print_qr(srv.url)
    print(f"Scan with the phone camera (same Wi-Fi), or open:\n  {srv.url}\nCtrl+C to quit.\n")
    t0 = time.time()
    warned = False
    try:
        while True:
            time.sleep(1)
            if not srv.hub.ever_connected and not warned and time.time() - t0 > 40:
                warned = True
                print("No phone connected yet. If the page won't load: allow the app on *Private* networks in the\n"
                      "Windows Firewall prompt, make sure this Wi-Fi is set to Private, or run it with --firewall")
    except KeyboardInterrupt:
        srv.stop()
        print("Bye.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cli", action="store_true", help="run in the terminal instead of opening the window")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--latency", type=int, default=None, choices=[40, 80, 160], help="phone buffer in ms")
    ap.add_argument("--chunk-ms", type=int, default=20)
    ap.add_argument("--firewall", action="store_true", help="add a Private-network firewall rule for the port (asks for admin)")
    args = ap.parse_args()
    cfg = load_config()
    port = args.port or cfg["port"]
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    if args.firewall:
        add_firewall_rule(port)
    elif args.cli:
        run_cli(port, args.latency or cfg["latency"], args.chunk_ms)
    else:
        run_gui()
