# Bosun

Control layer for the ARGUS-Q receiver family. Binds USB audio codecs, SDR
backends, and CAT-serial radios behind one capability-gated interface.

A bosun runs the rig and pipes the signals; he does not sail the boat. The
radios do the receiving, Bosun keeps the lines straight.

## Supported radios

| Model | Vendor | Control | Audio | TX |
|---|---|---|---|---|
| IC-9100 | Icom | CI-V 0x7C | USB codec | yes |
| IC-9700 | Icom | CI-V 0xA2 | USB codec | yes |
| FT-991A | Yaesu | ASCII CAT | USB codec | yes |
| AR-8200 | AOR | ASCII 9600 8N1 | line out | **no** |
| AR-8600 | AOR | ASCII 9600 8N1 | line out | **no** |

AOR units are receive-only: `ptt()` raises, `Cap.PTT` is absent, and the
AR-8200 masks out `Cap.SQUELCH` because it has no `SQ` command.

## Install

    python -m venv .venv && . .venv/bin/activate
    pip install -e ".[test,audio]"

## Use

    bosun probe
    bosun id --model IC-9700 --port /dev/ttyUSB0
    bosun set --model FT-991A --port /dev/ttyUSB0 --freq 14.225 --mode USB
    bosun scan --model IC-9700 --port /dev/ttyUSB0 --start 144.0 --stop 146.0 \
        --step 12.5 --squelch-gate
    bosun mem --model IC-9700 --port /dev/ttyUSB0 add --channel 1 --freq 145.5
    bosun mem --model IC-9700 push

Library:

    from bosun.radios import get
    from bosun.transport import SerialTransport

    radio = get("IC-9700")(SerialTransport("/dev/ttyUSB0", 19200))
    radio.connect()
    radio.set_frequency(144_300_000)

## Downloads

Ready-built Windows, Linux and Android packages come from GitHub Actions; see
[BUILD-PACKAGES.md](BUILD-PACKAGES.md). Requires Python 3.11+ when installing
from source.

## Configuration

Reads `$XDG_CONFIG_HOME/bosun/config.json` unless `--config` or `BOSUN_CONFIG`
says otherwise. `BOSUN_MODEL`, `BOSUN_PORT`, `BOSUN_TCP`, `BOSUN_BAUD`,
`BOSUN_LOG` override the file.

## Caveats

- Bind bridges by USB serial number; the tty index moves across reboots.
- CI-V echo suppression is on by default.
- IC-9700 band scope parsing is written from the manual but **not verified
  against hardware**.
- AOR memory frame shapes assume the two-digit channel format; verify before
  trusting `push`.
- API frequencies are Hz. `--freq` on the CLI is MHz.

## Status

Tune, mode, VFO, memory, scan, gain, squelch, attenuator, preamp, AGC, filter,
PTT and scope are implemented. No GUI, no demodulation, no decoders.

## Licence

MIT.
