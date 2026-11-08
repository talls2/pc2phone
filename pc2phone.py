#!/usr/bin/env python3
"""pc2phone: stream this PC's audio to a phone browser over Wi-Fi, no virtual cable.

    pip install pyaudiowpatch aiohttp qrcode numpy
    py -3 pc2phone.py            (add --firewall once if the phone can't connect)

PC: WASAPI loopback of the default output device -> stereo int16 -> WebSocket.
Phone: Safari opens the page from the QR code and plays with Web Audio.
"""
import argparse
import asyncio
import base64
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

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>PC audio</title>
<style>
 body{margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:18px;font:16px -apple-system,system-ui,sans-serif;background:#111;color:#eee}
 button{font:600 22px inherit;padding:22px 54px;border:0;border-radius:18px;background:#2d7ff9;color:#fff}
 button.on{background:#444}
 #st{font-size:18px} #info{font-size:13px;color:#999;font-variant-numeric:tabular-nums}
 select{font-size:15px;padding:6px;border-radius:8px}
</style></head><body>
<button id="b">Start</button>
<div id="st">Tap Start</div>
<div id="info"></div>
<label>Latency <select id="buf"><option value="40">low (40 ms)</option>
 <option value="80" selected>normal (80 ms)</option><option value="160">safe (160 ms)</option></select></label>
<audio id="silent" loop playsinline src="__SILENT__"></audio>
<script>
const RATE=__RATE__, KEY="__KEY__";
const $=id=>document.getElementById(id);
let ctx=null, ws=null, on=false, next=0, drops=0, unders=0, lastMsg=0, lock=null;
let target=0.08;
try{const v=localStorage.getItem('buf'); if(v){$('buf').value=v;}}catch(e){}
function readBuf(){target=+$('buf').value/1000; try{localStorage.setItem('buf',$('buf').value)}catch(e){}}
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
  ws.onclose=()=>{ if(on){say('Reconnecting… (rescan the QR if the PC script was restarted)'); setTimeout(connect,1000);} };
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


def capture_thread(loop, hub, chunk_ms):
    last_err = None
    while True:
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
            print(f"Capturing: {dev['name'].replace(' [Loopback]', '')} ({rate} Hz, {ch} ch)")
            last_err = None
            while True:
                time.sleep(2)
                if not stream.is_active():
                    raise RuntimeError("capture stream stopped")
                now = default_loopback()
                if now is None or now["name"] != dev["name"]:
                    print("Default output device changed, switching...")
                    break
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            if msg != last_err:
                print(f"Capture problem ({msg}); retrying...")
                last_err = msg
            time.sleep(2)
        finally:
            try:
                if stream:
                    stream.close()
            except Exception:
                pass
            p.terminate()


class Hub:
    def __init__(self):
        self.clients = set()
        self.rate = 0
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


def make_app(hub, key):
    async def index(request):
        if request.query.get("k") != key:
            return web.Response(status=403, text="Scan the QR code shown in the PC terminal.")
        html = (PAGE.replace("__RATE__", str(hub.rate)).replace("__KEY__", key)
                .replace("__SILENT__", silent_wav_uri()))
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def ws_handler(request):
        if request.query.get("k") != key:
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(heartbeat=5, compress=False)
        await ws.prepare(request)
        q = asyncio.Queue(maxsize=25)
        hub.clients.add(q)
        hub.ever_connected = True
        print(f"Phone connected: {request.remote} ({len(hub.clients)} listening)")
        sender = asyncio.create_task(send_loop(ws, q))
        try:
            async for _ in ws:
                pass
        finally:
            sender.cancel()
            hub.clients.discard(q)
            print(f"Phone disconnected: {request.remote} ({len(hub.clients)} listening)")
        return ws

    app = web.Application()
    app.add_routes([web.get("/", index), web.get("/ws", ws_handler)])
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


def print_qr(url):
    qr = qrcode.QRCode(border=2)
    qr.add_data(url)
    m = qr.get_matrix()
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
    print("Approve the Windows prompt, then run pc2phone again (without --firewall).")


async def main(args):
    hub = Hub()
    key = secrets.token_urlsafe(6)
    loop = asyncio.get_running_loop()
    threading.Thread(target=capture_thread, args=(loop, hub, args.chunk_ms), daemon=True).start()
    runner = web.AppRunner(make_app(hub, key), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, "0.0.0.0", args.port).start()
    except OSError as e:
        sys.exit(f"Can't listen on port {args.port} ({e}). Try --port 8766.")
    url = f"http://{lan_ip()}:{args.port}/?k={key}"
    print_qr(url)
    print(f"Scan with the iPhone camera (same Wi-Fi), or open:\n  {url}\nCtrl+C to quit.\n")
    t0 = time.time()
    warned = False
    while True:
        await asyncio.sleep(1)
        if not hub.ever_connected and not warned and time.time() - t0 > 40:
            warned = True
            print("No phone connected yet. If the page won't load: allow Python on *Private* networks in the\n"
                  "Windows Firewall prompt, make sure this Wi-Fi is set to Private, or run: py -3 pc2phone.py --firewall")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--chunk-ms", type=int, default=20, help="capture chunk size (default 20)")
    ap.add_argument("--firewall", action="store_true", help="add a Private-network firewall rule for the port (asks for admin)")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.firewall:
        add_firewall_rule(args.port)
        sys.exit()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("Bye.")
