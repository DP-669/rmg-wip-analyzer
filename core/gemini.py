"""
Gemini, with a gate in front of it.

The pattern is: upload raw bytes via the Files API, then before asking for any
analysis, make the model prove it can hear the file. It reports the duration it
hears; we compare that against the duration we measured locally. If the two do
not agree, the run stops and nothing is written.

This is the whole point of the app. A model that cannot hear the audio will
still produce a confident, well-structured, entirely invented analysis. The
gate is what makes the difference visible.
"""

import json
import time

from google import genai
from google.genai import types

from .audio import format_duration
from .prompts import GATE_PROMPT, build_analysis_prompt

MODEL_ID = "gemini-3.1-pro-preview"

# How far the model's duration may drift from the truth before we stop trusting
# it. Five seconds or five percent, whichever is more forgiving.
TOLERANCE_SECONDS = 5.0
TOLERANCE_FRACTION = 0.05

MAX_PROCESSING_WAIT = 300  # seconds


class GateFailure(Exception):
    """The model could not prove it heard the file. Nothing was analyzed."""


class AnalysisFailure(Exception):
    """The model heard the file but the analysis could not be read."""


def make_client(api_key: str) -> genai.Client:
    if not api_key:
        raise GateFailure(
            "No Gemini API key is configured. Add GEMINI_API_KEY to the app's "
            "secrets."
        )
    return genai.Client(api_key=api_key)


def _read_json(response, what: str) -> dict:
    text = (getattr(response, "text", "") or "").strip()
    if not text:
        raise AnalysisFailure(f"Gemini returned nothing for the {what}.")
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnalysisFailure(
            f"Gemini's {what} was not valid JSON. First 200 characters: "
            f"{text[:200]}"
        ) from exc


# ----------------------------------------------------------------- upload

def upload(client: genai.Client, local_path: str):
    """Send the raw bytes to Google and wait until they are ready to use."""
    remote = client.files.upload(file=local_path)

    waited = 0
    while "PROCESSING" in str(remote.state).upper():
        if waited >= MAX_PROCESSING_WAIT:
            raise GateFailure(
                "Google is still processing this file after five minutes. "
                "Stopped rather than wait longer."
            )
        time.sleep(3)
        waited += 3
        remote = client.files.get(name=remote.name)

    if "FAILED" in str(remote.state).upper():
        raise GateFailure(
            "Google could not process this audio file. It may be in an "
            "unsupported format or corrupt."
        )

    return remote


# ------------------------------------------------------------------- gate

def run_gate(client: genai.Client, remote_file, true_duration: float) -> dict:
    """
    Ask the model what it hears, then check that answer against the duration
    we measured locally. Raises GateFailure if they disagree.
    """
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=[GATE_PROMPT, remote_file],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0,
        ),
    )

    result = _read_json(response, "verification check")

    if not result.get("audio_access"):
        raise GateFailure(
            "Gemini reports it cannot hear this file. Nothing was analyzed."
        )

    claimed = result.get("estimated_duration_seconds")
    if not isinstance(claimed, (int, float)) or claimed <= 0:
        raise GateFailure(
            f"Gemini did not report a usable duration (it said: {claimed!r}). "
            "Without that there is no way to confirm it heard the file."
        )

    claimed = float(claimed)
    allowed = max(TOLERANCE_SECONDS, true_duration * TOLERANCE_FRACTION)
    drift = abs(claimed - true_duration)

    if result.get("source_type") == "silence":
        raise GateFailure("Gemini hears silence. Check the file plays.")

    if drift > allowed:
        raise GateFailure(
            f"Duration mismatch. The file is {format_duration(true_duration)} "
            f"but Gemini reports hearing {format_duration(claimed)} — a "
            f"{drift:.0f} second difference. It is not reliably hearing this "
            "track, so any analysis would be invented. Nothing was written."
        )

    result["_true_duration"] = true_duration
    result["_claimed_duration"] = claimed
    result["_drift_seconds"] = round(drift, 1)
    result["_tolerance_seconds"] = round(allowed, 1)
    return result


# --------------------------------------------------------------- analysis

def run_analysis(
    client: genai.Client,
    remote_file,
    catalog_code: str,
    brief: str = "",
) -> dict:
    """The real pass. Only reached once the gate has passed."""
    prompt = build_analysis_prompt(catalog_code, brief)

    response = client.models.generate_content(
        model=MODEL_ID,
        contents=[prompt, remote_file],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.4,
        ),
    )

    return _read_json(response, "analysis")


def release(client: genai.Client, remote_file) -> None:
    """Delete the uploaded copy from Google. Best effort."""
    try:
        client.files.delete(name=remote_file.name)
    except Exception:
        pass


# ------------------------------------------------------------ one track

def analyze_track(
    client: genai.Client,
    local_path: str,
    audio_info: dict,
    catalog_code: str,
    brief: str = "",
) -> dict:
    """
    Upload, gate, analyze, clean up. One track, its own session, no context
    carried from any other track.
    """
    remote = upload(client, local_path)
    try:
        gate = run_gate(client, remote, audio_info["duration_seconds"])
        analysis = run_analysis(client, remote, catalog_code, brief)
    finally:
        release(client, remote)

    return {"gate": gate, "analysis": analysis}
