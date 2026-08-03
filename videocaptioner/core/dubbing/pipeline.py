"""End-to-end subtitle dubbing pipeline."""

import hashlib
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Literal, Optional

from videocaptioner.core.speech import (
    SpeechProviderConfig,
    SynthesisRequest,
    create_speech_synthesizer,
)
from videocaptioner.core.speech.api_keys import parse_api_keys
from videocaptioner.core.utils.logger import setup_logger

from .audio import (
    change_tempo,
    create_silence_file,
    create_timeline_audio,
    get_audio_duration_ms,
    mux_dubbed_audio,
)
from .background_mix import mix_background
from .models import (
    DubbingConfig,
    DubbingResult,
    DubbingSegment,
    SpeakerProfile,
    elevenlabs_concurrent_per_key,
)
from .rewriter import rewrite_segments_if_needed
from .subtitle_parser import load_dubbing_segments
from .timeline import compute_timeline_placements, write_adjusted_subtitle
from .video_rate import (
    RatePlan,
    apply_video_rate,
    compute_rate_plan,
    get_video_duration_ms,
)

logger = setup_logger("dubbing")

ProgressCallback = Callable[[int, str], None]

# On Windows, suppress "Application Error" crash dialogs for ffmpeg.
_SUBPROCESS_KWARGS: dict = {}
if sys.platform == "win32":
    import ctypes

    ctypes.windll.kernel32.SetErrorMode(0x0003)
    _SUBPROCESS_KWARGS["creationflags"] = subprocess.CREATE_NO_WINDOW


def resolve_tts_worker_count(config: DubbingConfig, segment_count: int) -> int:
    """How many segment synthesis tasks may run in parallel."""
    if segment_count <= 0:
        return 1
    if config.provider == "elevenlabs":
        key_count = max(1, len(parse_api_keys(config.api_key)))
        per_key_cap = elevenlabs_concurrent_per_key(config.model)
        per_key = max(1, min(config.tts_workers, per_key_cap))
        worker_limit = key_count * per_key
    else:
        worker_limit = max(1, config.tts_workers)
    return max(1, min(worker_limit, segment_count))


def default_dubbed_audio_path(subtitle_path: str, response_format: str = "mp3") -> str:
    """与字幕同目录、同主文件名，扩展名为最终音频格式。"""
    stem = Path(subtitle_path).stem
    ext = response_format if response_format in ("mp3", "wav", "opus", "aac", "flac") else "mp3"
    return str(Path(subtitle_path).with_name(f"{stem}.{ext}"))


class DubbingPipeline:
    """Create a dubbed audio track, optionally muxed into a video."""

    def __init__(self, config: DubbingConfig):
        self.config = config
        speech_config = SpeechProviderConfig(
            provider=config.provider,
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
            default_voice=config.voice,
            response_format=self._provider_response_format(config),
            sample_rate=config.sample_rate,
            speed=config.speed,
            gain=config.gain,
            timeout=config.timeout,
            style_prompt=config.style_prompt,
            clone_audio_path=config.clone_audio_path,
            clone_audio_text=config.clone_audio_text,
            extra=config.extra,
        )
        self.synthesizer = create_speech_synthesizer(speech_config)

    def run(
        self,
        subtitle_path: str,
        output_audio_path: str,
        *,
        video_path: Optional[str] = None,
        output_video_path: Optional[str] = None,
        text_track: str = "auto",
        work_dir: Optional[str] = None,
        callback: Optional[ProgressCallback] = None,
    ) -> DubbingResult:
        cb = callback or (lambda _progress, _message: None)
        out_audio = Path(output_audio_path)
        work = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix=".dubbing_work_"))
        work.mkdir(parents=True, exist_ok=True)

        try:
            return self._run_inner(
                subtitle_path,
                out_audio,
                work,
                video_path=video_path,
                output_video_path=output_video_path,
                text_track=text_track,
                cb=cb,
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _run_inner(
        self,
        subtitle_path: str,
        out_audio: Path,
        work: Path,
        *,
        video_path: Optional[str],
        output_video_path: Optional[str],
        text_track: str,
        cb: ProgressCallback,
    ) -> DubbingResult:
        cb(2, "loading subtitles")
        segments = load_dubbing_segments(subtitle_path, text_track=text_track)
        if not segments:
            raise ValueError("No subtitle lines found for dubbing")
        self._apply_speakers(segments)

        warnings: list[str] = []
        instrument_path: Optional[str] = None
        if self.config.separate_vocal:
            if not video_path:
                warnings.append("separate_vocal 需要视频输入,已跳过人声分离")
                logger.warning("separate_vocal requires video_path; skipping separation")
            else:
                cb(4, "separating vocals")
                try:
                    from videocaptioner.core.separation import separate_vocals

                    source_audio = work / "source_audio.wav"
                    self._extract_video_audio(video_path, source_audio)
                    cb(5, "separating vocals and background")
                    _vocal, instrument_path = separate_vocals(
                        str(source_audio),
                        str(work),
                        progress=cb,
                    )
                    logger.info("分离人声/背景声完成: %s", instrument_path)
                except Exception as exc:
                    instrument_path = None
                    warnings.append(f"人声分离失败,已跳过: {exc}")
                    logger.warning("人声分离失败,已跳过: %s", exc)

        cb(8, "rewriting long lines")
        rewrite_segments_if_needed(segments, self.config)

        timeline_items: list[tuple[str, int]] = []
        total = len(segments)
        workers = resolve_tts_worker_count(self.config, total)
        completed = 0
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_pos = {
                executor.submit(self._process_segment, segment, work): pos
                for pos, segment in enumerate(segments)
            }
            ordered: list[DubbingSegment | None] = [None] * total
            for future in as_completed(future_to_pos):
                pos = future_to_pos[future]
                try:
                    segment = future.result()
                except Exception as exc:
                    # A segment that exhausts every API key must not abort the
                    # whole dub -- the quota already spent on other lines
                    # would be wasted. Drop in a silence placeholder, record a
                    # warning, and keep going so the run still produces audio.
                    original = segments[pos]
                    warnings.append(
                        f"字幕段 {original.index} 合成失败，已用静音占位：{exc}"
                    )
                    logger.warning(
                        "Segment %s synthesis failed; using silence placeholder: %s",
                        original.index,
                        exc,
                    )
                    segment = self._silence_fallback_segment(original, work)
                ordered[pos] = segment
                completed += 1
                cb(10 + int(completed / total * 75), f"synthesizing {completed}/{total}")

        segments = [seg for seg in ordered if seg is not None]
        adjusted_subtitle_path: Optional[Path] = None
        video_plan: Optional[RatePlan] = None
        if self.config.fixed_line_pause:
            # 固定停顿模式忽略原时间轴,不做视频变速。
            timeline_items, duration_ms = self._build_fixed_pause_timeline(segments, work)
        elif self.config.video_autorate and video_path:
            # 视频变速:由 rate plan 统一推导输出时间轴,音频放置从计划反推。
            slots = [(seg.start_ms, seg.end_ms) for seg in segments]
            audio_durations = [seg.fitted_duration_ms for seg in segments]
            video_duration_ms = get_video_duration_ms(video_path)
            plan, placements, extra_tempo = compute_rate_plan(
                slots,
                audio_durations,
                self.config.subtitle_gap_ms,
                video_duration_ms,
                self.config.max_video_slowdown,
            )
            # 对超限段二次压缩音频,保证音频必然放得下。
            for i, seg in enumerate(segments):
                if extra_tempo[i] > 1.0:
                    compressed = work / f"tempo_{seg.index:04d}.wav"
                    change_tempo(seg.fitted_path, str(compressed), extra_tempo[i])
                    seg.fitted_path = str(compressed)
                    seg.fitted_duration_ms = get_audio_duration_ms(seg.fitted_path)
            timeline_items = [
                (seg.fitted_path, placements[i][0]) for i, seg in enumerate(segments)
            ]
            duration_ms = plan.total_output_duration_ms
            adjusted_subtitle_path = Path(
                write_adjusted_subtitle(
                    segments,
                    placements,
                    str(out_audio.with_name(out_audio.stem + ".adjusted.srt")),
                )
            )
            video_plan = plan
        elif self.config.subtitle_gap_ms > 0:
            # 语音间隔模式:每条配音后插入静音,保留原时间轴整体顺延。
            placements = compute_timeline_placements(
                [seg.start_ms for seg in segments],
                [seg.fitted_duration_ms for seg in segments],
                self.config.subtitle_gap_ms,
            )
            timeline_items = [
                (seg.fitted_path, placements[i][0]) for i, seg in enumerate(segments)
            ]
            duration_ms = max(
                max(seg.end_ms for seg in segments),
                placements[-1][1],
            )
            adjusted_subtitle_path = Path(
                write_adjusted_subtitle(
                    segments,
                    placements,
                    str(out_audio.with_name(out_audio.stem + ".adjusted.srt")),
                )
            )
        else:
            for segment in segments:
                timeline_items.append((segment.fitted_path, segment.start_ms))
                overflow_ms = segment.start_ms + segment.fitted_duration_ms - segment.end_ms
                if overflow_ms > 80:
                    warning = f"segment {segment.index} exceeds target by {overflow_ms} ms"
                    segment.warning = warning
                    warnings.append(warning)

            duration_ms = max(
                max(seg.end_ms for seg in segments),
                max(seg.start_ms + seg.fitted_duration_ms for seg in segments),
            )
        cb(88, "assembling audio")
        create_timeline_audio(
            timeline_items,
            str(out_audio),
            duration_ms,
            volume=self.config.dubbed_audio_volume,
        )

        if self.config.embed_bgm and (
            instrument_path or self.config.extra_bgm_path
        ):
            cb(92, "mixing background audio")
            try:
                mixed = work / "dubbed_bgm.wav"
                mix_background(
                    str(out_audio),
                    instrument_path=instrument_path,
                    volume=self.config.bgm_volume,
                    loop=self.config.bgm_loop,
                    extra_bgm_path=self.config.extra_bgm_path or None,
                    output_path=str(mixed),
                )
                # 产物替代 out_audio 进入后续 mux / 烧录。
                shutil.move(str(mixed), str(out_audio))
            except Exception as exc:
                warnings.append(f"背景音回嵌失败,已跳过: {exc}")
                logger.warning("背景音回嵌失败,已跳过: %s", exc)

        out_video: Optional[Path] = None
        if video_path:
            if not output_video_path:
                base = Path(video_path)
                output_video_path = str(base.with_stem(base.stem + "_dubbed"))
            mux_source = video_path
            if self.config.video_autorate and video_plan is not None:
                cb(90, "adjusting video rate")
                rate_video = str(work / "rate.mp4")
                apply_video_rate(video_path, video_plan, rate_video, callback=cb)
                mux_source = rate_video
            cb(94, "muxing video")
            mux_dubbed_audio(
                mux_source,
                str(out_audio),
                output_video_path,
                mix_original_audio=self.config.mix_original_audio,
                original_audio_volume=self.config.original_audio_volume,
                dubbed_audio_volume=1.0,
            )
            out_video = Path(output_video_path)

            if self.config.embed_subtitle == "hard":
                from videocaptioner.core.utils.video_utils import add_subtitles

                cb(96, "burning subtitles")
                subtitle_source = adjusted_subtitle_path or Path(subtitle_path)
                baked = work / "baked.mp4"
                add_subtitles(str(out_video), str(subtitle_source), str(baked))
                # 跨盘符安全:replace 会抛 OSError,改用 shutil.move。
                shutil.move(str(baked), str(out_video))

        cb(100, "completed")
        return DubbingResult(
            audio_path=out_audio,
            video_path=out_video,
            segments=segments,
            duration_ms=duration_ms,
            warnings=warnings,
            adjusted_subtitle_path=adjusted_subtitle_path,
        )

    @staticmethod
    def _extract_video_audio(video_path: str, out_path: Path) -> None:
        """用 ffmpeg 从视频提取背景音回嵌所需的 44.1kHz 立体声 wav。

        与 ``separate_vocals`` 的模型输入要求一致(UVR 期望 44100Hz / 2 声道)。
        """
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            video_path,
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(out_path),
        ]
        subprocess.run(cmd, check=True, **_SUBPROCESS_KWARGS)

    def _apply_speakers(self, segments: list[DubbingSegment]) -> None:
        default_profile = self.config.speaker_profiles.get("default")
        for segment in segments:
            profile = self.config.speaker_profiles.get(segment.speaker) or default_profile
            if profile:
                self._apply_profile(segment, profile)
            if not segment.clone_audio_path and self.config.clone_audio_path:
                segment.clone_audio_path = self.config.clone_audio_path
            if not segment.clone_audio_text and self.config.clone_audio_text:
                segment.clone_audio_text = self.config.clone_audio_text
            if not segment.voice:
                segment.voice = self.config.voice or None
            if not segment.style_prompt:
                segment.style_prompt = self.config.style_prompt or None

    @staticmethod
    def _apply_profile(segment: DubbingSegment, profile: SpeakerProfile) -> None:
        if profile.voice:
            segment.voice = profile.voice
        if profile.clone_audio_path:
            segment.clone_audio_path = profile.clone_audio_path
        if profile.clone_audio_text:
            segment.clone_audio_text = profile.clone_audio_text
        if profile.style_prompt:
            segment.style_prompt = profile.style_prompt

    def _fit_segment(self, segment: DubbingSegment, work_dir: Path) -> str:
        source = segment.synthesized_path
        if (
            self.config.fixed_line_pause
            or self.config.fit_mode == "none"
            or not segment.target_duration_ms
        ):
            return source
        target_ms = max(100, segment.target_duration_ms - self.config.target_padding_ms)
        if segment.synthesized_duration_ms <= target_ms:
            segment.speed_factor = 1.0
            return source
        required = segment.synthesized_duration_ms / target_ms
        factor = min(required, self.config.max_speed)
        segment.speed_factor = factor
        out_path = work_dir / f"{segment.index:04d}_{self._segment_hash(segment)}_fit.wav"
        change_tempo(source, str(out_path), factor)
        return str(out_path)

    def _build_fixed_pause_timeline(
        self,
        segments: list[DubbingSegment],
        work_dir: Path,
    ) -> tuple[list[tuple[str, int]], int]:
        """Lay segments end-to-end with a silent pause between each line.

        Ignores the SRT timeline entirely: each segment's fitted audio is
        placed at the running cursor, followed by a silence file of
        ``fixed_line_pause_ms`` (except after the last line). Returns the
        timeline items and the total duration in milliseconds.
        """
        timeline: list[tuple[str, int]] = []
        pause_ms = max(0, self.config.fixed_line_pause_ms)
        cursor = 0
        for i, segment in enumerate(segments):
            timeline.append((segment.fitted_path, cursor))
            cursor += segment.fitted_duration_ms
            if i < len(segments) - 1 and pause_ms > 0:
                silence_path = create_silence_file(str(work_dir / f"pause_{i:04d}.wav"), pause_ms)
                timeline.append((silence_path, cursor))
                cursor += pause_ms
        return timeline, cursor

    def _process_segment(self, segment: DubbingSegment, work: Path) -> DubbingSegment:
        raw_path = work / f"{segment.index:04d}_{self._segment_hash(segment)}_raw.{self._provider_extension()}"
        reusable_raw = self.config.use_cache and self._valid_audio_path(raw_path)
        if reusable_raw:
            segment.synthesized_path = str(raw_path)
            segment.synthesized_duration_ms = get_audio_duration_ms(segment.synthesized_path)
            if self._needs_duration_retry(segment, segment.synthesized_duration_ms):
                raw_path.unlink(missing_ok=True)
                reusable_raw = False
        if not reusable_raw:
            segment.synthesized_path = self._synthesize_with_duration_retry(segment, raw_path)
        segment.synthesized_duration_ms = get_audio_duration_ms(segment.synthesized_path)
        segment.fitted_path = self._fit_segment(segment, work)
        segment.fitted_duration_ms = get_audio_duration_ms(segment.fitted_path)
        return segment

    def _silence_fallback_segment(self, segment: DubbingSegment, work: Path) -> DubbingSegment:
        """Build a silence-placeholder segment for a failed synthesis.

        Keeps the timeline intact (a target-duration slice of silence) so the
        rest of the dub can proceed without the failed segment shifting later
        lines. The gap is flagged via ``segment.warning`` and the pipeline
        warning list so the user knows which line was dropped.
        """
        duration_ms = max(100, segment.target_duration_ms or 1000)
        silence_path = work / f"{segment.index:04d}_silence_fallback.wav"
        create_silence_file(str(silence_path), duration_ms)
        segment.synthesized_path = str(silence_path)
        segment.synthesized_duration_ms = duration_ms
        segment.fitted_path = str(silence_path)
        segment.fitted_duration_ms = duration_ms
        segment.warning = "合成失败，已用静音占位"
        return segment

    def _synthesize_with_duration_retry(self, segment: DubbingSegment, raw_path: Path) -> str:
        last_path = ""
        original_style = segment.style_prompt
        for attempt in range(3):
            raw_path.unlink(missing_ok=True)
            style_prompt = original_style
            if attempt == 1 and original_style:
                style_prompt = "自然、清晰地朗读。"
            elif attempt == 2:
                style_prompt = None
            result = self.synthesizer.synthesize(
                SynthesisRequest(
                    text=segment.text_for_tts,
                    output_path=str(raw_path),
                    voice=segment.voice,
                    style_prompt=style_prompt,
                    clone_audio_path=segment.clone_audio_path,
                    clone_audio_text=segment.clone_audio_text,
                )
            )
            last_path = result.output_path
            duration_ms = get_audio_duration_ms(last_path)
            if not self._needs_duration_retry(segment, duration_ms):
                return last_path
        return last_path

    def _needs_duration_retry(self, segment: DubbingSegment, duration_ms: int) -> bool:
        if (
            self.config.fixed_line_pause
            or self.config.fit_mode != "tempo"
            or not segment.target_duration_ms
        ):
            return False
        target_ms = max(100, segment.target_duration_ms - self.config.target_padding_ms)
        if duration_ms <= target_ms * self.config.max_speed:
            return False
        # Very short subtitles occasionally produce pathological long TTS output.
        return len(segment.text_for_tts.strip()) <= 40

    def _provider_extension(self) -> str:
        if self.config.provider == "gemini":
            return "wav"
        if self.config.provider == "edge":
            return "mp3"
        if self.config.provider == "elevenlabs":
            return "mp3"
        if self.config.provider in ("dots", "voxcpm"):
            return "wav"
        return self.config.response_format

    @staticmethod
    def _provider_response_format(
        config: DubbingConfig,
    ) -> Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]:
        if config.provider == "gemini":
            return "wav"
        if config.provider == "edge":
            return "mp3"
        if config.provider == "elevenlabs":
            return "mp3"
        if config.provider in ("dots", "voxcpm"):
            return "wav"
        return config.response_format

    @staticmethod
    def _segment_hash(segment: DubbingSegment) -> str:
        raw = "|".join(
            [
                segment.text_for_tts,
                segment.voice or "",
                segment.style_prompt or "",
                segment.clone_audio_path or "",
                segment.clone_audio_text or "",
            ]
        )
        return hashlib.md5(raw.encode()).hexdigest()[:10]

    @staticmethod
    def _valid_audio_path(path: Path) -> bool:
        if not path.exists() or path.stat().st_size <= 0:
            return False
        try:
            get_audio_duration_ms(str(path))
            return True
        except Exception:
            return False

