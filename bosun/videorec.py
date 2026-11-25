"""Video recording: MP4 through ffmpeg when available, otherwise Motion-JPEG AVI.

MJPEG AVI needs only Pillow (already used by the desktop app) and plays in
VLC, Windows Media Player and most editors. If an ffmpeg program is found
(on PATH, or from the optional imageio-ffmpeg package), H.264 MP4 is written.
"""

from __future__ import annotations

import io
import pathlib
import shutil
import struct
import subprocess
import time

import numpy as np


def find_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _to_rgb(frame) -> np.ndarray:
    if hasattr(frame, "convert"):  # PIL image
        frame = np.asarray(frame.convert("RGB"))
    frame = np.asarray(frame)
    if frame.ndim == 2:
        frame = np.repeat(frame[..., None], 3, axis=2)
    return np.ascontiguousarray(frame[..., :3].astype(np.uint8))


def _fit(frame: np.ndarray, w: int, h: int) -> np.ndarray:
    if frame.shape[1] == w and frame.shape[0] == h:
        return frame
    ys = np.linspace(0, frame.shape[0] - 1, h).astype(int)
    xs = np.linspace(0, frame.shape[1] - 1, w).astype(int)
    return frame[ys][:, xs]


class _MJPEGAvi:
    """Minimal streaming AVI (RIFF) writer with JPEG frames."""

    def __init__(self, path: pathlib.Path, w: int, h: int, fps: float, quality: int = 85):
        from PIL import Image  # noqa: F401  (fail early if Pillow is missing)

        self.path, self.w, self.h, self.fps, self.quality = path, w, h, fps, quality
        self.f = open(path, "wb")  # noqa: SIM115 - open for the recording's lifetime
        self.index: list[tuple[int, int]] = []
        self.max_size = 0
        self._header()

    def _header(self) -> None:
        us = int(1_000_000 / self.fps)
        avih = struct.pack("<IIIIIIIIII4I", us, 0, 0, 0x10, 0, 0, 1, 0, self.w, self.h,
                           0, 0, 0, 0)
        # stream header: rate/scale = frames per second
        strh = struct.pack("<4s4sIHHIIIIIIIIhhhh", b"vids", b"MJPG", 0, 0, 0, 0,
                           1000, int(round(self.fps * 1000)), 0, 0, 0, 0xFFFFFFFF, 0,
                           0, 0, self.w, self.h)
        strf = struct.pack("<IiiHH4sIiiII", 40, self.w, self.h, 1, 24, b"MJPG",
                           self.w * self.h * 3, 0, 0, 0, 0)
        strl = (b"LIST" + struct.pack("<I", 4 + 8 + len(strh) + 8 + len(strf)) + b"strl"
                + b"strh" + struct.pack("<I", len(strh)) + strh
                + b"strf" + struct.pack("<I", len(strf)) + strf)
        hdrl_body = b"hdrl" + b"avih" + struct.pack("<I", len(avih)) + avih + strl
        self.f.write(b"RIFF\0\0\0\0AVI ")
        self.f.write(b"LIST" + struct.pack("<I", len(hdrl_body)) + hdrl_body)
        self._avih_pos = 12 + 8 + 4 + 8  # start of avih data
        self.f.write(b"LIST\0\0\0\0movi")
        self._movi_pos = self.f.tell() - 12  # start of the LIST movi chunk

    def write(self, frame: np.ndarray) -> None:
        from PIL import Image

        buf = io.BytesIO()
        Image.fromarray(frame).save(buf, "JPEG", quality=self.quality)
        data = buf.getvalue()
        if len(data) % 2:
            data += b"\0"
        offset = self.f.tell() - (self._movi_pos + 8)
        self.f.write(b"00dc" + struct.pack("<I", len(data)) + data)
        self.index.append((offset, len(data)))
        self.max_size = max(self.max_size, len(data))

    def close(self) -> None:
        f = self.f
        movi_end = f.tell()
        f.seek(self._movi_pos + 4)
        f.write(struct.pack("<I", movi_end - self._movi_pos - 8))
        f.seek(movi_end)
        idx = b"".join(b"00dc" + struct.pack("<III", 0x10, off, size)
                       for off, size in self.index)
        f.write(b"idx1" + struct.pack("<I", len(idx)) + idx)
        end = f.tell()
        f.seek(4)
        f.write(struct.pack("<I", end - 8))
        # frame counts: avih total frames, strh length, buffer size
        f.seek(self._avih_pos + 16)
        f.write(struct.pack("<I", len(self.index)))
        f.seek(self._avih_pos + 28)
        f.write(struct.pack("<I", self.max_size))
        strh_data = self._avih_pos + 56 + 12 + 8  # after avih, LIST strl header, 'strh'+len
        f.seek(strh_data + 32)
        f.write(struct.pack("<I", len(self.index)))
        f.seek(strh_data + 36)
        f.write(struct.pack("<I", self.max_size))
        f.close()


class _FFmpegMP4:
    def __init__(self, path: pathlib.Path, w: int, h: int, fps: float, exe: str):
        self.path = path
        self.proc = subprocess.Popen(
            [exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{w}x{h}", "-r", f"{fps:g}", "-i", "-", "-c:v", "libx264",
             "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             str(path)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def write(self, frame: np.ndarray) -> None:
        self.proc.stdin.write(frame.tobytes())

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        finally:
            self.proc.wait(30)


class VideoRecorder:
    """Add frames as they are drawn; frames are paced to `fps` (extra frames
    dropped, gaps filled by repeating the last frame) so playback runs at real
    speed."""

    def __init__(self, base: pathlib.Path, fps: float = 10, prefer_mp4: bool = True) -> None:
        self.base, self.fps = pathlib.Path(base), fps
        self.prefer_mp4 = prefer_mp4
        self._writer = None
        self.path: pathlib.Path | None = None
        self.frames = 0
        self._t0: float | None = None
        self._last: np.ndarray | None = None
        self.size: tuple[int, int] | None = None

    @property
    def kind(self) -> str:
        return "MP4" if self.path is not None and self.path.suffix == ".mp4" \
            else "AVI (Motion JPEG)"

    def _open(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        w, h = w - w % 2, h - h % 2  # H.264 needs even sizes
        self.size = (w, h)
        exe = find_ffmpeg() if self.prefer_mp4 else None
        if exe:
            self.path = self.base.with_name(self.base.name + ".mp4")
            try:
                self._writer = _FFmpegMP4(self.path, w, h, self.fps, exe)
                return
            except OSError:
                pass
        self.path = self.base.with_name(self.base.name + ".avi")
        self._writer = _MJPEGAvi(self.path, w, h, self.fps)

    def add(self, frame, now: float | None = None) -> None:
        frame = _to_rgb(frame)
        if self._writer is None:
            self._open(frame)
            self._t0 = now if now is not None else time.monotonic()
        frame = _fit(frame, *self.size)
        now = now if now is not None else time.monotonic()
        due = int((now - self._t0) * self.fps) + 1  # frames that should exist by now
        if self.frames >= due:
            self._last = frame
            return
        while self.frames < due - 1 and self._last is not None:  # fill gaps
            self._writer.write(self._last)
            self.frames += 1
        self._writer.write(frame)
        self.frames += 1
        self._last = frame

    def close(self) -> pathlib.Path | None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        return self.path


class WindowRecorder:
    """Records a Tk widget's area of the screen (e.g. the faceplate)."""

    def __init__(self, widget, base: pathlib.Path, fps: float = 8) -> None:
        self.widget = widget
        self.rec = VideoRecorder(base, fps)
        self._job = None
        self.error: str | None = None

    def start(self) -> None:
        self._tick()

    def _tick(self) -> None:
        try:
            from PIL import ImageGrab

            w = self.widget
            x, y = w.winfo_rootx(), w.winfo_rooty()
            img = ImageGrab.grab(bbox=(x, y, x + w.winfo_width(), y + w.winfo_height()),
                                 all_screens=True)
            self.rec.add(img)
        except Exception as exc:  # e.g. Wayland without screen capture
            self.error = str(exc)
            return
        self._job = self.widget.after(int(1000 / self.rec.fps), self._tick)

    def stop(self) -> pathlib.Path | None:
        if self._job is not None:
            self.widget.after_cancel(self._job)
            self._job = None
        return self.rec.close()
