# pc2phone

Stream your Windows PC's audio to a phone browser over Wi-Fi. No virtual cable.

```
pip install pyaudiowpatch aiohttp qrcode numpy
py -3 pc2phone.py
```

Scan the QR code with the phone camera (same Wi-Fi), tap **Start**.

- Captures the default output device with WASAPI loopback and follows it if the default changes.
- The phone plays with Web Audio, keeps a small jitter buffer (40/80/160 ms) and drops chunks when it falls behind.
- iPhone silent switch: uses `navigator.audioSession` plus a silent looping `<audio>` element.
- Firewall: allow Python on Private networks, or run `py -3 pc2phone.py --firewall` once (asks for admin).
