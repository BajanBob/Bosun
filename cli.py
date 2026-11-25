"""Bosun CLI."""

from __future__ import annotations

import argparse
import json
import sys

from . import config as config_mod
from . import sdr, usb
from .errors import BosunError
from .memory import Memory, MemoryBank, pull_bank, push_bank
from .radios import catalogue, get
from .radios.registry import DRIVERS
from .scan import ScanEngine
from .transport import SerialTransport, TCPTransport
from .version import __version__


def _transport(args):
    if args.tcp:
        host, _, port = args.tcp.partition(":")
        return TCPTransport(host, int(port))
    if not args.port:
        raise SystemExit("--port or --tcp required")
    return SerialTransport(args.port, args.baud or get(args.model).default_baud)


def _radio(args):
    radio = get(args.model)(_transport(args))
    radio.connect()
    return radio


def _bank(args) -> MemoryBank:
    path = args.bank or str(config_mod.default_bank_path(args.model))
    cls = get(args.model)
    return MemoryBank.open(args.model, path, max_channel=cls.max_channel, modes=set(cls.modes))


def cmd_list(args):
    for e in catalogue():
        print(f"{e['model']:<10} {e['vendor']:<6} {e['bands_mhz']} {e['modes']}")


def cmd_probe(args):
    print("audio codecs:")
    for name in usb.list_codecs():
        print(f"  {name}")
    print("serial bridges:")
    for b in usb.enumerate_bridges():
        print(f"  {b.device} {b.vid:04x}:{b.pid:04x} {b.serial} {b.description}")
    print("sdr devices:")
    found = sdr.available()
    if not found:
        print("  none")
    for key, devs in found.items():
        for d in devs:
            print(f"  {key}:{d}")


def cmd_id(args):
    radio = _radio(args)
    try:
        print(json.dumps(radio.status(), indent=2))
    finally:
        radio.disconnect()


def cmd_set(args):
    radio = _radio(args)
    try:
        if args.freq:
            radio.set_frequency(args.freq * 1e6)
        if args.mode:
            radio.set_mode(args.mode)
        if args.af is not None:
            radio.set_af_gain(args.af)
        if args.rf is not None:
            radio.set_rf_gain(args.rf)
        if args.squelch is not None:
            radio.set_squelch(args.squelch)
        if args.attenuator is not None:
            radio.set_attenuator(args.attenuator)
        print(json.dumps(radio.status(), indent=2))
    finally:
        radio.disconnect()


def cmd_mem(args):
    bank = _bank(args)
    radio = _radio(args)
    try:
        if args.action == "push":
            print(f"wrote {push_bank(radio, bank)} channels")
        elif args.action == "pull":
            channels = [int(c) for c in (args.channels or "1-10").split(",")]
            print(f"read {pull_bank(radio, bank, channels)} channels")
        elif args.action == "add":
            bank.put(Memory(args.channel, args.freq * 1e6, args.mode or "FM", args.label))
            bank.save()
            print(f"channel {args.channel} stored")
        elif args.action == "drop":
            bank.drop(args.channel)
            bank.save()
        else:
            for mem in bank.channels.values():
                print(f"{mem.channel:>3} {mem.frequency / 1e6:>12.6f} "
                      f"{mem.mode:<6} {mem.label:<9} {'skip' if mem.skip else ''}")
        for a, b in bank.duplicates():
            print(f"warning: {a} and {b} share a frequency", file=sys.stderr)
    finally:
        radio.disconnect()


def cmd_scan(args):
    radio = _radio(args)
    engine = ScanEngine(
        radio, mode="range" if args.start else "list", dwell=args.dwell,
        resume=args.resume, resume_after=args.resume_after, max_cycles=args.cycles,
        detector=(lambda: radio.squelch_open()) if args.squelch_gate else None,
        on_hit=lambda hz: print(f"HIT {hz / 1e6:.6f} MHz"),
    )
    if args.start:
        engine.use_range(args.start * 1e6, args.stop * 1e6, args.step * 1e3)
    else:
        engine.use_bank(_bank(args))
    print(f"scanning {engine.mode} dwell={engine.dwell}s resume={engine.resume}")
    try:
        engine.run()
    except KeyboardInterrupt:
        engine.stop()
    finally:
        s = engine.stats
        print(f"steps={s.steps} hits={s.hits} cycles={s.cycles} errors={s.errors}")
        radio.disconnect()


def main(argv=None):
    p = argparse.ArgumentParser(prog="bosun", description="Radio control for ARGUS-Q")
    p.add_argument("--version", action="version", version=f"bosun {__version__}")
    p.add_argument("--config")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    sub.add_parser("probe").set_defaults(fn=cmd_probe)

    for name, fn in (("id", cmd_id), ("set", cmd_set), ("scan", cmd_scan), ("mem", cmd_mem)):
        s = sub.add_parser(name)
        s.add_argument("--model", required=True, choices=sorted(DRIVERS))
        s.add_argument("--port")
        s.add_argument("--tcp")
        s.add_argument("--baud", type=int)
        s.add_argument("--bank")
        s.add_argument("--freq", type=float, help="MHz")
        s.add_argument("--mode")
        s.add_argument("--af", type=float)
        s.add_argument("--rf", type=float)
        s.add_argument("--squelch", type=float)
        s.add_argument("--attenuator", type=lambda v: v.lower() in ("1", "on", "true"))
        s.add_argument("--channel", type=int, default=1)
        s.add_argument("--channels")
        s.add_argument("--label", default="")
        s.add_argument("--start", type=float)
        s.add_argument("--stop", type=float)
        s.add_argument("--step", type=float, default=25.0)
        s.add_argument("--dwell", type=float, default=0.6)
        s.add_argument("--resume", choices=("time", "stop", "off"), default="time")
        s.add_argument("--resume-after", type=float, default=3.0)
        s.add_argument("--cycles", type=int, default=0)
        s.add_argument("--squelch-gate", action="store_true")
        s.set_defaults(fn=fn)

    sub.choices["mem"].add_argument(
        "action", choices=("show", "add", "drop", "push", "pull"), nargs="?", default="show"
    )
    args = p.parse_args(argv)
    cfg = config_mod.load(args.config)
    config_mod.setup_logging(cfg)
    if not getattr(args, "model", None) and cfg.model:
        args.model = cfg.model
    try:
        args.fn(args)
    except BosunError as exc:
        print(f"bosun: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
