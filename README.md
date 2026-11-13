# Speaker Anywhere

Play your Windows PC's audio on any device that has a browser and a speaker, over Wi-Fi. Phones, tablets, laptops, other PCs. Nothing to install on the receiving device and no virtual cable.

## App

Run `SpeakerAnywhere-Setup.exe`, open **Speaker Anywhere**, press **Start**. The window expands to show a QR code and a link. Scan the code with a phone camera, or open the link on any other device on the same Wi-Fi, then tap **Start** on the page.

- Captures the default output device with WASAPI loopback and follows it if the default changes.
- The receiving device plays with Web Audio and keeps a small jitter buffer (40/80/160 ms), dropping chunks when it falls behind.
- iPhone silent switch: uses `navigator.audioSession` plus a silent looping `<audio>` element.
- The installer adds a Private-network firewall rule for the app.

## From source

```
pip install pyaudiowpatch aiohttp qrcode numpy
py -3 speaker_anywhere.py            # window
py -3 speaker_anywhere.py --cli      # terminal
py -3 speaker_anywhere.py --firewall # allow the port on Private networks (asks for admin)
```

## Build the installer

```
pip install pyinstaller
py -3 -m PyInstaller --noconfirm --clean --windowed --onedir --name SpeakerAnywhere --collect-all pyaudiowpatch --distpath build/dist --workpath build/work --specpath build speaker_anywhere.py
ISCC.exe installer.iss        # Inno Setup 6 -> output/SpeakerAnywhere-Setup.exe
```
