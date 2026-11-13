import asyncio
import re
import struct
import subprocess
import sys
import time

import aiohttp


async def main(log_path, play):
    deadline = time.time() + 30
    url = None
    while time.time() < deadline and not url:
        m = re.search(r"http://\S+", open(log_path, encoding="utf-8", errors="replace").read())
        url = m.group(0) if m else None
        time.sleep(0.5)
    assert url, "server did not print a URL"
    async with aiohttp.ClientSession() as s:
        r = await s.get(url.replace("127.0.0.1", "127.0.0.1"))
        assert r.status == 200, r.status
        async with s.ws_connect(url.replace("http", "ws").replace("/?", "/ws?")) as ws:
            time.sleep(1)
            tone = subprocess.Popen(play)
            chunks, peak, rates = 0, 0, set()
            end = time.time() + 6
            while time.time() < end:
                try:
                    msg = await ws.receive(timeout=3)
                except asyncio.TimeoutError:
                    break
                if msg.type == aiohttp.WSMsgType.BINARY:
                    rates.add(struct.unpack("<I", msg.data[:4])[0])
                    samples = struct.unpack("<%dh" % ((len(msg.data) - 4) // 2), msg.data[4:])
                    peak = max(peak, max(abs(x) for x in samples))
                    chunks += 1
            tone.terminate()
    print("chunks", chunks, "rates", rates, "peak", peak)
    assert chunks > 20 and peak > 1000, "no audio came through"


asyncio.run(main(sys.argv[1], sys.argv[2:]))
