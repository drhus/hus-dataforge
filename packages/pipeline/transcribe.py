"""transcribe: faster-whisper wrapper for the youtube_channel pipeline.

Reads pending audio files written by the youtube_channel spider, runs them
through faster-whisper with VAD preprocessing, and folds the transcript
back into the raw record so the downstream clean/export stages see audio
records the same way they see scraped text.

Model defaults:
  - language: ar
  - model: env DATAFORGE_WHISPER_MODEL or 'medium' (CPU-friendly)
  - compute_type: int8 (CPU); int8_float16 on GPU
  - initial_prompt: built per-record from channel + subject metadata to bias
    toward dialect spelling and zajal-specific vocabulary

Idempotency: a video's audio is only transcribed once per (model, prompt)
combination. The transcript JSON next to the audio carries the model name
and a hash of the initial_prompt; we skip a video whose existing transcript
matches both."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from packages.api import projects_store
from packages.api.settings import DATA_DIR
from packages.engine.spec import project_spec_from_dict

log = logging.getLogger(__name__)

_DEFAULT_MODEL = os.environ.get("DATAFORGE_WHISPER_MODEL", "medium")
_DEFAULT_COMPUTE_TYPE = os.environ.get("DATAFORGE_WHISPER_COMPUTE_TYPE", "int8")
_DEFAULT_DEVICE = os.environ.get("DATAFORGE_WHISPER_DEVICE", "cpu")


def _audio_dir(slug: str, channel_slug: str) -> Path:
    return DATA_DIR / slug / "raw_audio" / channel_slug


def _transcript_path(audio_path: Path) -> Path:
    return audio_path.with_suffix(".transcript.json")


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


def _build_prompt(source_name: str, subject_name: str | None) -> str:
    """Whisper initial_prompt — biases toward Lebanese/Syrian/Palestinian
    colloquial spelling and away from MSA hallucination. Keep under ~200
    chars so whisper's prompt-token budget stays available for the audio
    context."""
    base = "تسجيل قصيدة زجل أو شعر شعبي باللهجة اللبنانية أو السورية أو الفلسطينية."
    if subject_name:
        return f"{base} الشاعر: {subject_name}."
    return base


def _load_index(audio_dir: Path) -> list[dict]:
    p = audio_dir / "_index.jsonl"
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _latest_index_by_video(entries: list[dict]) -> dict[str, dict]:
    """index.jsonl is append-only — the latest entry per video_id wins."""
    out: dict[str, dict] = {}
    for e in entries:
        vid = e.get("video_id")
        if vid:
            out[vid] = e
    return out


def _existing_transcript_matches(
    transcript_path: Path, model: str, prompt_hash: str
) -> bool:
    if not transcript_path.exists():
        return False
    try:
        data = json.loads(transcript_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return (
        data.get("whisper_model") == model
        and data.get("whisper_prompt_hash") == prompt_hash
    )


def transcribe_project(
    slug: str,
    *,
    source_filter: list[str] | None = None,
    model: str = _DEFAULT_MODEL,
    language: str = "ar",
    compute_type: str = _DEFAULT_COMPUTE_TYPE,
    device: str = _DEFAULT_DEVICE,
    max_videos: int | None = None,
) -> dict:
    """Transcribe pending audio across all youtube_channel sources.

    Returns: {"by_source": {source_name: count}, "total": int, "model": str}
    """
    raw_cfg = projects_store.get_project(slug).config
    if "_yaml" in raw_cfg and isinstance(raw_cfg["_yaml"], str):
        import yaml

        raw_cfg = yaml.safe_load(raw_cfg["_yaml"]) or {}
    spec = project_spec_from_dict(slug, raw_cfg)

    yt_sources = [
        s
        for s in spec.sources
        if s.type == "youtube_channel"
        and (source_filter is None or s.name in source_filter)
    ]
    if not yt_sources:
        return {"by_source": {}, "total": 0, "model": model, "note": "no youtube_channel sources"}

    # Lazy import — only pay the load cost when we actually transcribe.
    from faster_whisper import WhisperModel

    log.info("transcribe: loading faster-whisper %s (device=%s compute=%s)",
             model, device, compute_type)
    wm = WhisperModel(model, device=device, compute_type=compute_type)

    by_source: dict[str, int] = {}
    total = 0
    for source in yt_sources:
        audio_dir = _audio_dir(slug, source.name)
        if not audio_dir.exists():
            log.info("transcribe: %s — no audio dir yet (skip)", source.name)
            by_source[source.name] = 0
            continue

        entries = _latest_index_by_video(_load_index(audio_dir))
        # Stable order by video_id so smoke runs are deterministic.
        pending = [e for e in entries.values() if e.get("status") == "downloaded"]
        pending.sort(key=lambda e: e.get("video_id", ""))

        prompt = _build_prompt(source.name, source.subject)
        ph = _prompt_hash(prompt)
        count = 0
        for entry in pending:
            if max_videos is not None and total >= max_videos:
                break
            audio_path_str = entry.get("audio_path")
            if not audio_path_str:
                continue
            audio_path = Path(audio_path_str)
            if not audio_path.exists():
                log.warning("transcribe: %s missing audio %s", entry["video_id"], audio_path)
                continue
            tp = _transcript_path(audio_path)
            if _existing_transcript_matches(tp, model, ph):
                continue

            log.info("transcribe: %s/%s (%s)", source.name, entry["video_id"], audio_path.name)
            segments, info = wm.transcribe(
                str(audio_path),
                language=language,
                initial_prompt=prompt,
                vad_filter=True,
            )
            seg_records: list[dict] = []
            full_text_parts: list[str] = []
            for seg in segments:
                seg_records.append(
                    {
                        "start": round(float(seg.start), 3),
                        "end": round(float(seg.end), 3),
                        "text": seg.text.strip(),
                        "avg_logprob": (
                            round(float(seg.avg_logprob), 4)
                            if seg.avg_logprob is not None
                            else None
                        ),
                        "no_speech_prob": (
                            round(float(seg.no_speech_prob), 4)
                            if seg.no_speech_prob is not None
                            else None
                        ),
                    }
                )
                full_text_parts.append(seg.text.strip())

            transcript = {
                "video_id": entry["video_id"],
                "audio_path": str(audio_path),
                "whisper_model": model,
                "whisper_prompt": prompt,
                "whisper_prompt_hash": ph,
                "language": info.language,
                "language_probability": round(float(info.language_probability), 4),
                "duration": round(float(info.duration), 3),
                "segments": seg_records,
                "text": "\n".join(full_text_parts).strip(),
            }
            tp.write_text(
                json.dumps(transcript, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # Update _index.jsonl with status=transcribed (append a new entry;
            # latest-wins reader handles deduplication).
            with (audio_dir / "_index.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            **entry,
                            "status": "transcribed",
                            "whisper_model": model,
                            "whisper_prompt_hash": ph,
                            "transcript_path": str(tp),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

            count += 1
            total += 1
        by_source[source.name] = count

    return {"by_source": by_source, "total": total, "model": model}
