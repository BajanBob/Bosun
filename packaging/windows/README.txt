BOSUN FOR WINDOWS

Keep this whole folder together (Bosun.exe needs the _internal folder next
to it). Or use Bosun-Windows-Desktop-Setup.exe, which installs it for you.

Bosun.exe      Desktop app. Double-click to open. Choose your radio, pick its
               COM port (USB serial) or enter a network address, then Connect.
bosun-cli.exe  Command-line tool for scripting (run "bosun-cli --help").

USB serial radios need the USB driver for your interface (Silicon Labs CP210x,
FTDI or the radio maker's driver). The COM port is shown in Device Manager under
"Ports (COM & LPT)".

RTL-SDR dongles: install the WinUSB driver once with Zadig (zadig.akeo.ie),
choosing "Bulk-In, Interface (Interface 0)".

Recordings and spectrum captures are saved in "Bosun Recordings" in your user
folder. Setup > Setup wizard walks you through radio, SDR and audio.

If Bosun ever closes unexpectedly, it writes what happened to
%LOCALAPPDATA%\Bosun\bosun.log (paste that path into Explorer's address bar).

Windows may show a SmartScreen warning the first time because the app is not
code-signed. Choose "More info" then "Run anyway".
