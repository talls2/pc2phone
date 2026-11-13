# pc2phone

Stream your Windows PC's audio to a phone browser over Wi-Fi. No virtual cable.

## App

Run `PC2Phone-Setup.exe`, open **PC to Phone**, press **Start**. The window expands to show a QR code; scan it with the phone camera (same Wi-Fi) and tap **Start** on the page.

- Captures the default output device with WASAPI loopback and follows it if the default changes.
- The phone plays with Web Audio and keeps a small jitter buffer (40/80/160 ms), dropping chunks when it falls behind.
- iPhone silent switch: uses `navigator.audioSession` plus a silent looping `<audio>` element.
- The installer adds a Private-network firewall rule for the app.

## From source

```
pip install pyaudiowpatch aiohttp qrcode numpy
py -3 pc2phone.py            # window
py -3 pc2phone.py --cli      # terminal
py -3 pc2phone.py --firewall # allow the port on Private networks (asks for admin)
```

## Build the installer

```
pip install pyinstaller
py -3 -m PyInstaller --noconfirm --clean --windowed --onedir --name PC2Phone --collect-all pyaudiowpatch --distpath build/dist --workpath build/work --specpath build pc2phone.py
ISCC.exe installer.iss        # Inno Setup 6 -> output/PC2Phone-Setup.exe
```
