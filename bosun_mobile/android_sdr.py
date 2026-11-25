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
