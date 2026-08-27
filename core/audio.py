"""
Local audio inspection.

The duration measured here is ground truth. Everything Gemini says about the
file is checked against it. If we cannot measure the file locally, we do not
run the analysis at all — an unverified analysis is worse than none.
"""

import json
import os
import shutil
import subprocess

# rMG WIP spec: MP3, 48 kHz, 320 kbps CBR.
SPEC = {"container": "mp3", "sample_rate": 48000, "bitrate_kbps": 320}

ACCEPTED_EXTENSIONS = {".mp3", ".wav", ".aif", ".aiff", ".flac", ".m4a", ".aac"}


class AudioError(Exception):
    """The file could not be read as audio."""


def _ffprobe(path: str) -> dict:
    """Full stream and format info via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries",
            "format=duration,bit_rate,format_name:stream=codec_name,"
            "sample_rate,channels,bit_rate",
            "-select_streams", "a:0",
            "-of", "json",
            path,
        ],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise AudioError(
            "This file could not be read as audio. It is most likely corrupt, "
            "or it is not actually an audio file."
        )
    return json.loads(result.stdout)


def _mutagen_duration(path: str) -> float:
    """Fallback when ffprobe is missing. Duration only."""
    try:
        from mutagen import File as MutagenFile
    except ImportError as exc:
        raise AudioError(
            "Neither ffprobe nor mutagen is available, so the duration cannot "
            "be measured. Install ffmpeg on the server."
        ) from exc

    audio = MutagenFile(path)
    if audio is None or not getattr(audio, "info", None):
        raise AudioError("This file could not be read as audio.")
    return float(audio.info.length)


def inspect(path: str) -> dict:
    """
    Measure the file. Returns duration, format facts, and whether it meets
    the WIP submission spec.

    Raises AudioError if the file is not readable audio.
    """
    if not os.path.exists(path):
        raise AudioError("The file is missing from disk.")

    size_bytes = os.path.getsize(path)
    if size_bytes < 20_000:
        raise AudioError(
            f"This file is only {size_bytes / 1024:.0f} KB. That is not a track "
            "— the download probably returned an error page instead of audio."
        )

    info = {
        "size_mb": round(size_bytes / (1024 * 1024), 2),
        "codec": None,
        "sample_rate": None,
        "channels": None,
        "bitrate_kbps": None,
    }

    if shutil.which("ffprobe"):
        probed = _ffprobe(path)
        fmt = probed.get("format", {})
        streams = probed.get("streams", [])
        stream = streams[0] if streams else {}

        try:
            duration = float(fmt.get("duration"))
        except (TypeError, ValueError) as exc:
            raise AudioError(
                "ffprobe read the file but found no duration. It may be "
                "truncated or corrupt."
            ) from exc

        bitrate = stream.get("bit_rate") or fmt.get("bit_rate")
        info.update(
            codec=stream.get("codec_name"),
            sample_rate=int(stream["sample_rate"]) if stream.get("sample_rate") else None,
            channels=stream.get("channels"),
            bitrate_kbps=round(int(bitrate) / 1000) if bitrate else None,
        )
    else:
        duration = _mutagen_duration(path)

    if duration <= 0.5:
        raise AudioError(
            f"This file is {duration:.1f} seconds long. There is nothing to analyze."
        )

    info["duration_seconds"] = round(duration, 2)
    info["duration_display"] = format_duration(duration)
    info["spec"] = _check_spec(info, path)
    return info


# ffprobe reports codecs, not the names people use for the files.
FRIENDLY_CODEC = {
    "pcm_s16le": "WAV", "pcm_s24le": "WAV", "pcm_s32le": "WAV",
    "pcm_f32le": "WAV", "pcm_s16be": "AIFF", "pcm_s24be": "AIFF",
    "flac": "FLAC", "alac": "ALAC", "aac": "AAC", "mp3": "MP3",
}


def _check_spec(info: dict, path: str) -> dict:
    """Compare against the WIP submission spec. Informational, never blocking."""
    ext = os.path.splitext(path)[1].lower()
    issues = []

    codec = (info.get("codec") or "").lower()
    if codec and codec != "mp3":
        label = FRIENDLY_CODEC.get(codec, codec.upper())
        issues.append(f"{label} rather than MP3")
    elif not codec and ext not in (".mp3",):
        issues.append(f"{ext.lstrip('.').upper()} rather than MP3")

    if info.get("sample_rate") and info["sample_rate"] != SPEC["sample_rate"]:
        issues.append(f"{info['sample_rate'] / 1000:.1f} kHz rather than 48 kHz")

    if info.get("bitrate_kbps") and codec == "mp3":
        if abs(info["bitrate_kbps"] - SPEC["bitrate_kbps"]) > 16:
            issues.append(f"{info['bitrate_kbps']} kbps rather than 320 kbps")

    return {"compliant": not issues, "issues": issues}


def format_duration(seconds: float) -> str:
    """Seconds to M:SS."""
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}:{secs:02d}"


def parse_timecode(value: str) -> float:
    """'2:24' or '0:07' to seconds. Returns -1 if unparseable."""
    if not isinstance(value, str):
        return -1.0
    parts = value.strip().split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return float(parts[0])
    except (ValueError, IndexError):
        return -1.0
