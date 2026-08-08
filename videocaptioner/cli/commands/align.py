"""align command — align a correct transcript onto an ASR subtitle timeline.

Given an ASR-generated subtitle (accurate timestamps, rough text) and a correct
transcript, produce a subtitle with the correct text on the ASR's timeline using
character-level DTW alignment (see ``videocaptioner.core.alignment``).
"""

from argparse import Namespace
from pathlib import Path

from videocaptioner.cli import exit_codes as EXIT
from videocaptioner.cli import output
from videocaptioner.core.alignment import align_text_to_asr
from videocaptioner.core.asr.asr_data import ASRData


def run(args: Namespace, config: dict) -> int:
    subtitle_path = Path(args.subtitle)
    if not subtitle_path.exists():
        output.error(f"Subtitle file not found: {subtitle_path}")
        return EXIT.FILE_NOT_FOUND

    # Read the user's correct transcript.
    if args.text_file:
        text_path = Path(args.text_file)
        if not text_path.exists():
            output.error(f"Transcript file not found: {text_path}")
            return EXIT.FILE_NOT_FOUND
        user_text = text_path.read_text(encoding="utf-8")
    else:
        user_text = args.text or ""
    if not user_text.strip():
        output.error("No transcript text provided. Use --text or --text-file.")
        return EXIT.USAGE_ERROR

    output.info("Loading ASR subtitle (source of accurate timestamps)...")
    try:
        asr_data = ASRData.from_subtitle_file(str(subtitle_path))
    except Exception as exc:
        output.error(f"Failed to read subtitle file: {output.clean_error(str(exc))}")
        return EXIT.RUNTIME_ERROR
    if not asr_data.segments:
        output.error("Subtitle file contained no segments.")
        return EXIT.RUNTIME_ERROR

    output.info(
        f"Aligning transcript ({len(user_text)} chars) onto {len(asr_data.segments)} "
        f"ASR segments via DTW..."
    )
    stats: dict = {}
    try:
        aligned = align_text_to_asr(
            asr_data, user_text, max_chars=args.max_chars, stats=stats
        )
    except Exception as exc:
        output.error(f"Alignment failed: {output.clean_error(str(exc))}")
        return EXIT.RUNTIME_ERROR

    if not aligned.segments:
        output.error("Alignment produced no segments.")
        return EXIT.RUNTIME_ERROR

    # Low-confidence warning: the transcript and the ASR text differ a lot, so
    # the generated timeline is likely inaccurate.
    match_rate = stats.get("match_rate")
    if match_rate is not None and match_rate < 85.0:
        output.warn(
            f"Alignment confidence low ({match_rate:.0f}%) — "
            "timestamps may be inaccurate; check the transcript matches the audio"
        )

    output_path = (
        Path(args.output)
        if args.output
        else subtitle_path.with_name(subtitle_path.stem + ".aligned.srt")
    )
    aligned.save(str(output_path))
    if getattr(args, "quiet", False):
        print(output_path)
    else:
        output.success(f"Aligned {len(aligned.segments)} segments -> {output_path}")
    return EXIT.SUCCESS
