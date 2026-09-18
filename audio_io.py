"""
audio_io.py
------------
Decoding, peak extraction and trim/export helpers for the built-in audio
editor.

WHY THIS MODULE EXISTS
----------------------
Nothing in here touches tkinter, so every function is safe to call from a
worker thread (see audio_editor.py, which does exactly that). Keeping the
audio work in its own module also means the editor UI stays a view layer,
matching how the rest of the project is organised.

DEPENDENCY CHOICE
-----------------
We use `soundfile` (a small ctypes/cffi binding around libsndfile) plus
`numpy`. The wheels published on PyPI bundle libsndfile itself, and since
libsndfile 1.1 that bundle includes the MPEG (mp3) and Vorbis (ogg)
codecs, so:

  * reading AND writing mp3/ogg/wav/flac works out of the box,
  * a Windows user needs nothing extra installed -- in particular no
    ffmpeg, which is what ruled out pydub/audioread for this project.

`pygame` is already a dependency but only exposes playback, not sample
access or encoding, so it can't produce a waveform or write a trimmed
file; it stays responsible for preview playback only.

FORMAT SUPPORT IS NEVER ASSUMED
-------------------------------
`can_read`/`can_write` ask the installed libsndfile what it actually
supports rather than hard-coding a list, so an older build that lacks mp3
encoding is reported honestly to the user instead of failing at save time.
"""

from __future__ import annotations

import math
import os
import tempfile
import numpy as np
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

_IMPORT_ERROR: Optional[str] = None
try:  # pragma: no cover - exercised implicitly by the editor
    import numpy as np
    import soundfile as sf
except Exception as exc:  # noqa: BLE001 - any import problem means "no editor"
    np = None  # type: ignore[assignment]
    sf = None  # type: ignore[assignment]
    _IMPORT_ERROR = str(exc)


class AudioError(Exception):
    """A user-facing audio problem (bad file, unwritable format, ...)."""


class Cancelled(Exception):
    """Raised by the worker helpers when the caller asked them to stop."""


# Extensions the editor offers, mapped to the libsndfile format name used
# when writing. Everything the rest of the app scans (.mp3/.ogg/.wav) is
# here; .flac is included because libsndfile handles it natively and it
# costs nothing.
FORMAT_BY_EXT = {
    ".wav": "WAV",
    ".mp3": "MP3",
    ".ogg": "OGG",
    ".oga": "OGG",
    ".flac": "FLAC",
}
LOSSY_EXTENSIONS = {".mp3", ".ogg", ".oga"}
DEFAULT_EXTENSIONS = (".mp3", ".ogg", ".wav")

#: Shortest selection the editor allows, in seconds.
MIN_SELECTION_SECONDS = 0.05

#: Frames read per iteration when scanning/exporting (~6 s of 44.1 kHz).
_READ_BLOCK = 262144


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------
def available() -> bool:
    """True when soundfile + numpy imported cleanly."""
    return sf is not None and np is not None


def unavailable_reason() -> str:
    return (
        "The audio editor needs the 'soundfile' and 'numpy' packages.\n\n"
        "Install them with:\n"
        "    python -m pip install -r requirements.txt\n\n"
        f"Import error: {_IMPORT_ERROR}"
    )


def _require() -> None:
    if not available():
        raise AudioError(unavailable_reason())


def _formats() -> dict:
    try:
        return sf.available_formats()
    except Exception:  # noqa: BLE001
        return {}


def can_read(ext: str) -> bool:
    """libsndfile uses the same backends for reading and writing, so this
    is the same question as can_write for our purposes -- kept separate so
    call sites read clearly.
    """
    return can_write(ext)


def can_write(ext: str) -> bool:
    if not available():
        return False
    fmt = FORMAT_BY_EXT.get((ext or "").lower())
    return bool(fmt) and fmt in _formats()


def writable_extensions() -> Tuple[str, ...]:
    return tuple(e for e in FORMAT_BY_EXT if can_write(e))


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AudioInfo:
    path: str
    samplerate: int
    channels: int
    frames: int
    duration: float
    format: str
    subtype: str

    @property
    def ext(self) -> str:
        return os.path.splitext(self.path)[1].lower()

    @property
    def lossy(self) -> bool:
        return self.ext in LOSSY_EXTENSIONS

    def describe(self) -> str:
        channels = {1: "mono", 2: "stereo"}.get(
            self.channels, f"{self.channels} ch")
        return (f"{self.format} · {self.samplerate} Hz · {channels} · "
                f"{format_time(self.duration)}")


def probe(path: str) -> AudioInfo:
    """Read an audio file's header. Raises AudioError with a message meant
    for a dialog box, never a raw traceback.
    """
    _require()
    if not path:
        raise AudioError("No audio file was selected.")
    if not os.path.isfile(path):
        raise AudioError(f"The file no longer exists:\n{path}")
    try:
        info = sf.info(path)
    except Exception as exc:  # noqa: BLE001 - libsndfile raises several types
        raise AudioError(
            f"'{os.path.basename(path)}' could not be decoded.\n\n"
            "It may be corrupt, or in a format this build of libsndfile "
            f"doesn't support.\n\nDetails: {exc}"
        ) from exc
    if info.frames <= 0 or info.samplerate <= 0:
        raise AudioError(
            f"'{os.path.basename(path)}' contains no decodable audio.")
    return AudioInfo(
        path=path,
        samplerate=int(info.samplerate),
        channels=int(info.channels),
        frames=int(info.frames),
        duration=float(info.frames) / float(info.samplerate),
        format=str(info.format),
        subtype=str(info.subtype or ""),
    )


# ---------------------------------------------------------------------------
# Waveform peaks
# ---------------------------------------------------------------------------
@dataclass
class Waveform:
    """Min/max peak pairs over a fixed number of buckets.

    The file is scanned once, at a resolution well above any realistic
    window width; redrawing at a different widget width just re-buckets
    these arrays (see `resample`) instead of touching the disk again.
    """

    info: AudioInfo
    mins: "np.ndarray"
    maxs: "np.ndarray"
    peak: float

    def resample(self, width: int):
        """Return (mins, maxs) arrays of exactly `width` entries, scaled so
        the loudest peak in the file reaches 1.0 (a flat-looking waveform
        for a quiet track is not useful for finding trim points).
        """
        width = max(1, int(width))
        n = len(self.mins)
        if n == 0:
            zeros = np.zeros(width, dtype="float32")
            return zeros, zeros.copy()
        idx = np.linspace(0, n, width, endpoint=False).astype(np.intp)
        np.clip(idx, 0, n - 1, out=idx)
        mins = np.minimum.reduceat(self.mins, idx)
        maxs = np.maximum.reduceat(self.maxs, idx)
        scale = 1.0 / self.peak if self.peak > 1e-4 else 1.0
        return np.clip(mins * scale, -1.0, 1.0), np.clip(maxs * scale, -1.0, 1.0)


def compute_waveform(
    path: str,
    buckets: int = 3000,
    progress: Optional[Callable[[float], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Waveform:
    """Scan `path` and return its peak envelope.

    Streams the file in blocks so a long track never has to be held in
    memory in full, and calls `progress(0..1)` / checks `should_cancel()`
    between blocks. Meant to be run on a worker thread.
    """
    _require()
    info = probe(path)

    buckets = max(64, int(buckets))
    frames_per_bucket = max(1, int(math.ceil(info.frames / buckets)))
    n_buckets = int(math.ceil(info.frames / frames_per_bucket))

    mins = np.zeros(n_buckets, dtype="float32")
    maxs = np.zeros(n_buckets, dtype="float32")

    bucket = 0
    pending = np.zeros(0, dtype="float32")
    done_frames = 0
    block_size = max(frames_per_bucket, _READ_BLOCK)

    try:
        with sf.SoundFile(path) as handle:
            while True:
                if should_cancel is not None and should_cancel():
                    raise Cancelled()
                block = handle.read(block_size, dtype="float32",
                                    always_2d=True)
                if len(block) == 0:
                    break
                mono = block.mean(
                    axis=1) if block.shape[1] > 1 else block[:, 0]
                pending = mono if len(pending) == 0 else np.concatenate(
                    (pending, mono))
                while len(pending) >= frames_per_bucket and bucket < n_buckets:
                    chunk = pending[:frames_per_bucket]
                    mins[bucket] = chunk.min()
                    maxs[bucket] = chunk.max()
                    bucket += 1
                    pending = pending[frames_per_bucket:]
                done_frames += len(block)
                if progress is not None and info.frames:
                    progress(min(1.0, done_frames / info.frames))
    except Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AudioError(
            f"'{os.path.basename(path)}' could not be read.\n\nDetails: {exc}"
        ) from exc

    if len(pending) and bucket < n_buckets:
        mins[bucket] = pending.min()
        maxs[bucket] = pending.max()
        bucket += 1

    if bucket < n_buckets:  # short read (some decoders round frame counts)
        mins = mins[:max(bucket, 1)]
        maxs = maxs[:max(bucket, 1)]

    peak = float(max(abs(float(mins.min())), abs(float(maxs.max()))))
    if progress is not None:
        progress(1.0)
    return Waveform(info=info, mins=mins, maxs=maxs, peak=peak)


# ---------------------------------------------------------------------------
# Trim / export
# ---------------------------------------------------------------------------
def validate_range(start: float, end: float, duration: float) -> Tuple[float, float]:
    """Clamp + sanity-check a trim range, raising AudioError for ranges a
    user could not have meant (negative, reversed, past the end).
    """
    try:
        start = float(start)
        end = float(end)
    except (TypeError, ValueError) as exc:
        raise AudioError("The start and end times must be numbers.") from exc
    if start < 0 or end < 0:
        raise AudioError("Times cannot be negative.")
    if start > duration or end > duration:
        raise AudioError(
            f"Times cannot be past the end of the audio "
            f"({format_time(duration)}).")
    if end - start < MIN_SELECTION_SECONDS:
        raise AudioError(
            "The selected region is empty or the end is before the start.\n\n"
            f"It must be at least {MIN_SELECTION_SECONDS:g} seconds long.")
    return start, end


def _pick_subtype(fmt: str, src_format: str, src_subtype: str) -> Optional[str]:
    """Keep the source's subtype when we're writing the *same* format (so a
    16-bit wav stays 16-bit), otherwise let libsndfile pick the default.

    Only inheriting within the same format matters: sf.check_format() will
    happily accept e.g. WAV + MPEG_LAYER_III (a legal container/codec pair)
    which libsndfile then refuses to *encode*, so carrying a subtype across
    formats turns "render an mp3 selection to a preview wav" into a crash.
    """
    try:
        if src_subtype and fmt == src_format and sf.check_format(fmt, src_subtype):
            return src_subtype
        return sf.default_subtype(fmt)
    except Exception:  # noqa: BLE001
        return None


def export_segment(
    src: str,
    dest: str,
    start_seconds: float,
    end_seconds: float,
    out_format: Optional[str] = None,
    progress: Optional[Callable[[float], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> str:
    """Write [start, end) of `src` to `dest` and return `dest`.

    Streams frame blocks straight from the decoder into the encoder, so
    memory use is constant regardless of track length, and writes through
    a temporary file in the destination directory followed by os.replace,
    so a failure (or a crash) can never leave a half-written file where a
    good one used to be. That is what makes "Replace original" safe.

    Meant to be run on a worker thread.
    """
    _require()
    info = probe(src)
    start_seconds, end_seconds = validate_range(
        start_seconds, end_seconds, info.duration)

    ext = os.path.splitext(dest)[1].lower()
    fmt = out_format or FORMAT_BY_EXT.get(ext)
    if not fmt:
        raise AudioError(
            f"'{ext or dest}' is not an audio format this editor can write.\n\n"
            "Supported: " + ", ".join(sorted(writable_extensions())))
    if fmt not in _formats():
        raise AudioError(
            f"This installation of libsndfile cannot write {fmt} files.\n\n"
            "Choose one of: " + ", ".join(sorted(writable_extensions())))

    start_frame = max(0, int(round(start_seconds * info.samplerate)))
    end_frame = min(info.frames, int(round(end_seconds * info.samplerate)))
    total = end_frame - start_frame
    if total <= 0:
        raise AudioError("The selected region contains no audio.")

    folder = os.path.dirname(os.path.abspath(dest)) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".rm_trim_", suffix=ext or ".tmp",
                               dir=folder)
    os.close(fd)

    try:
        with sf.SoundFile(src) as fin:
            fin.seek(start_frame)
            subtype = _pick_subtype(fmt, info.format, info.subtype)
            with sf.SoundFile(tmp, "w", samplerate=fin.samplerate,
                              channels=fin.channels, format=fmt,
                              subtype=subtype) as fout:
                written = 0
                while written < total:
                    if should_cancel is not None and should_cancel():
                        raise Cancelled()
                    block = fin.read(min(_READ_BLOCK, total - written),
                                     dtype="float32", always_2d=True)
                    if len(block) == 0:
                        break
                    fout.write(block)
                    written += len(block)
                    if progress is not None:
                        progress(min(1.0, written / total))
        os.replace(tmp, dest)
    except Cancelled:
        _silent_unlink(tmp)
        raise
    except Exception as exc:  # noqa: BLE001
        _silent_unlink(tmp)
        raise AudioError(
            f"Could not write '{os.path.basename(dest)}'.\n\n"
            "The original file was left untouched.\n\n"
            f"Details: {exc}"
        ) from exc
    if progress is not None:
        progress(1.0)
    return dest


def export_preview_wav(
    src: str,
    start_seconds: float,
    end_seconds: float,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> str:
    """Render the selection to a throwaway 16-bit wav in the system temp
    directory, for pygame to play. WAV is used deliberately: it is always
    writable, always readable by pygame, decodes instantly, and never
    re-compresses anything the user might later save.

    The caller owns the returned path and must delete it.
    """
    _require()
    fd, tmp = tempfile.mkstemp(prefix="rm_preview_", suffix=".wav")
    os.close(fd)
    try:
        export_segment(src, tmp, start_seconds, end_seconds,
                       out_format="WAV", should_cancel=should_cancel)
    except BaseException:
        _silent_unlink(tmp)
        raise
    return tmp


def silent_unlink(path: str) -> None:
    """Best-effort delete, for temp files nobody should care about."""
    try:
        os.unlink(path)
    except OSError:
        pass


#: Internal alias kept for readability at the call sites above.
_silent_unlink = silent_unlink


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------
def resolve_song_path(folder: str, stem: str, extensions=DEFAULT_EXTENSIONS):
    """The audio file a songpack entry's song name refers to, or None.

    Mirrors ui_enhancements.resolve_selected_path so the editor can be
    opened even when that enhancement isn't installed.
    """
    if not folder or not stem:
        return None
    for ext in extensions:
        candidate = os.path.join(folder, stem + ext)
        if os.path.isfile(candidate):
            return candidate
    return None


def format_time(seconds: float, with_ms: bool = True) -> str:
    """m:ss.mmm -- compact enough for a button label, precise enough to
    type back into the start/end boxes.
    """
    try:
        seconds = max(0.0, float(seconds))
    except (TypeError, ValueError):
        seconds = 0.0
    minutes, rest = divmod(seconds, 60.0)
    if with_ms:
        return f"{int(minutes)}:{rest:06.3f}"
    return f"{int(minutes)}:{int(rest):02d}"


def parse_time(text: str) -> float:
    """Accept '12', '12.5', '1:23', '1:23.456' or '01:02:03.5'.

    Raises ValueError (not AudioError) so the caller can decide whether a
    typo deserves a dialog or just a status-bar nudge.
    """
    text = (text or "").strip().lower().rstrip("s").strip()
    if not text:
        raise ValueError("empty time")
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError("too many ':' separators")
    total = 0.0
    for part in parts:
        part = part.strip()
        if not part:
            raise ValueError("missing value around ':'")
        total = total * 60.0 + float(part)
    if total < 0:
        raise ValueError("negative time")
    return total
