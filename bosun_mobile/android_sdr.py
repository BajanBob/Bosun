"""Start the Android "Rtl-sdr driver" app (marto.rtl_tcp_andro) for a USB dongle.

The driver asks the user for USB permission, opens the RTL-SDR, and serves it
on 127.0.0.1 with the rtl_tcp protocol, which Bosun then reads.
"""

from __future__ import annotations

DRIVER_PACKAGE = "marto.rtl_tcp_andro"
PORT = 1234
REQUEST_CODE = 4321


def on_android() -> bool:
    try:
        import java  # noqa: F401  (Chaquopy bridge, only present on Android)
    except ImportError:
        return False
    return True


def _activity(app):
    native = getattr(getattr(app, "_impl", None), "native", None)
    if native is not None and hasattr(native, "startActivity"):
        return native
    from java import jclass

    return jclass("org.beeware.android.MainActivity").singletonThis


def driver_installed(app) -> bool:
    if not on_android():
        return False
    try:
        _activity(app).getPackageManager().getPackageInfo(DRIVER_PACKAGE, 0)
        return True
    except Exception:
        return False


def start_driver(app, rate: int = 1_024_000, port: int = PORT) -> None:
    """Launch the driver. It shows the USB permission prompt if needed."""
    from java import jclass

    Intent = jclass("android.content.Intent")
    Uri = jclass("android.net.Uri")
    intent = Intent(Intent.ACTION_VIEW)
    intent.setData(Uri.parse(f"iqsrc://-a 127.0.0.1 -p {port} -s {int(rate)}"))
    _activity(app).startActivityForResult(intent, REQUEST_CODE)


def open_driver_store_page(app) -> None:
    """Open the driver's page (F-Droid, Play Store or any store app)."""
    from java import jclass

    Intent = jclass("android.content.Intent")
    Uri = jclass("android.net.Uri")
    activity = _activity(app)
    for url in (f"market://details?id={DRIVER_PACKAGE}",
                f"https://f-droid.org/packages/{DRIVER_PACKAGE}/"):
        try:
            activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            return
        except Exception:
            continue


# Common RTL2832U dongles (vendor, product).
RTL_IDS = {(0x0BDA, 0x2832), (0x0BDA, 0x2838), (0x0CCD, 0x00A9), (0x0CCD, 0x00B3),
           (0x0CCD, 0x00D3), (0x185B, 0x0620), (0x185B, 0x0650), (0x1D19, 0x1101),
           (0x1F4D, 0xB803), (0x1F4D, 0xC803), (0x1B80, 0xD3A4)}


def usb_devices(app) -> list[tuple[int, int, str]]:
    """(vendor, product, name) for every USB device on the phone's port."""
    if not on_android():
        return []
    from java import jclass

    Context = jclass("android.content.Context")
    manager = _activity(app).getSystemService(Context.USB_SERVICE)
    out = []
    for dev in manager.getDeviceList().values():
        out.append((int(dev.getVendorId()), int(dev.getProductId()),
                    str(dev.getProductName() or dev.getDeviceName())))
    return out


def rtl_dongles(app) -> list[str]:
    return [name for vid, pid, name in usb_devices(app) if (vid, pid) in RTL_IDS]
