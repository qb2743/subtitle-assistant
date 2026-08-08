"""视频字幕全流程线程: 转录 -> 说话人筛选 -> 翻译/洗稿 -> 配音与画面对齐。"""

from __future__ import annotations

import copy
import json
import shutil
import threading
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from videocaptioner.core.asr.asr_data import ASRData, ASRDataSeg
from videocaptioner.core.diarization.assign import (
    remap_speakers_ms,
    speaker_sidecar_path,
    write_speaker_json,
)
from videocaptioner.core.dubbing.models import DubbingSegment
from videocaptioner.core.dubbing.narrator_filter import filter_narrator_subtitles
from videocaptioner.core.dubbing.subtitle_parser import load_dubbing_segments
from videocaptioner.core.entities import SubtitleLayoutEnum, TranscribeTask
from videocaptioner.core.split.split import SubtitleSplitter, preprocess_segments
from videocaptioner.core.utils.logger import setup_logger
from videocaptioner.ui.common.config import cfg
from videocaptioner.ui.dubbing_config_builder import diarization_language_from_transcribe
from videocaptioner.ui.task_factory import TaskFactory
from videocaptioner.ui.thread.dubbing_interface_thread import DubbingInterfaceThread
from videocaptioner.ui.thread.subtitle_thread import SubtitleThread
from videocaptioner.ui.thread.transcript_thread import TranscriptThread

logger = setup_logger("video_translation_thread")

REVIEW_WAIT_TIMEOUT_SECONDS = 40


def _job_output_dir(
    video: Path, configured_root: str, subtitle_action: str = "translate"
) -> Path:
    root = Path(configured_root.strip()) if configured_root.strip() else video.parent
    action = "洗稿" if subtitle_action == "rewrite" else "翻译"
    return root / f"{video.stem}_视频{action}"


def _organize_outputs(output_dir: Path, video: Path, translated_path: Path) -> Path:
    """Keep final deliverables in the root and move pipeline artifacts aside."""
    intermediate = output_dir / "中间文件"
    intermediate.mkdir(parents=True, exist_ok=True)
    adjusted = output_dir / f"{translated_path.stem}.adjusted.srt"
    final_subtitle = output_dir / f"{video.stem}_最终字幕.srt"
    shutil.copy2(adjusted if adjusted.is_file() else translated_path, final_subtitle)
    if adjusted.is_file():
        target = intermediate / adjusted.name
        target.unlink(missing_ok=True)
        shutil.move(str(adjusted), str(target))
    for extension in ("mp3", "wav", "opus", "aac", "flac"):
        audio = output_dir / f"{translated_path.stem}.{extension}"
        if audio.is_file():
            target = intermediate / audio.name
            target.unlink(missing_ok=True)
            shutil.move(str(audio), str(target))
    return final_subtitle


def _write_dubbing_subtitle(path: Path, subtitle_data: dict) -> Path:
    """Write only the translated/rewritten field used by TTS."""
    if subtitle_data:
        ASRData.from_json(subtitle_data).to_srt(
            layout=SubtitleLayoutEnum.ONLY_TRANSLATE,
            save_path=str(path),
        )
    return path


def _write_dubbing_speaker_sidecar(
    path: Path,
    subtitle_data: dict,
    source_intervals: list[tuple[int, int]],
    source_speakers: list[str],
    narrator_speaker: str = "",
) -> Path | None:
    """Map source speaker metadata onto the final edited subtitle timeline."""
    sidecar = speaker_sidecar_path(path)
    if not subtitle_data or not source_intervals or not source_speakers:
        sidecar.unlink(missing_ok=True)
        return None

    final_data = ASRData.from_json(subtitle_data)
    target_intervals = [
        (segment.start_time, segment.end_time) for segment in final_data.segments
    ]
    forced_speaker = str(narrator_speaker or "").strip()
    if forced_speaker:
        labels = [forced_speaker] * len(target_intervals)
    else:
        labels = remap_speakers_ms(
            source_intervals,
            source_speakers,
            target_intervals,
        )
    write_speaker_json(labels, sidecar)
    return sidecar


def _narrator_review_path(source_subtitle: Path) -> Path:
    return source_subtitle.with_name(source_subtitle.stem + "-narrator-review.json")


def _narrator_dropped_path(source_subtitle: Path) -> Path:
    return source_subtitle.with_name(source_subtitle.stem + "-narrator-dropped.srt")


def _merge_word_level_segments(
    segments: list[DubbingSegment],
    speakers: list[str],
    *,
    max_cjk: int = 25,
    max_words: int = 18,
) -> tuple[list[DubbingSegment], list[str]]:
    """Merge word timestamps into reviewable utterances without crossing speakers."""
    if not segments:
        return [], []
    word_data = ASRData(
        [ASRDataSeg(seg.text, seg.start_ms, seg.end_ms) for seg in segments]
    )
    if not word_data.is_word_timestamp():
        return segments, list(speakers)

    labels = [str(value or "").strip() for value in speakers]
    labels.extend([""] * (len(segments) - len(labels)))
    merged: list[DubbingSegment] = []
    merged_speakers: list[str] = []
    splitter = SubtitleSplitter(
        thread_num=1,
        model="",
        max_word_count_cjk=max_cjk,
        max_word_count_english=max_words,
    )
    try:
        group_start = 0
        while group_start < len(segments):
            speaker = labels[group_start]
            group_end = group_start + 1
            while group_end < len(segments) and labels[group_end] == speaker:
                group_end += 1
            source = preprocess_segments(
                [
                    ASRDataSeg(segment.text, segment.start_ms, segment.end_ms)
                    for segment in segments[group_start:group_end]
                ],
                need_lower=False,
            )
            for sentence in splitter._process_by_rules(source):
                merged.append(
                    DubbingSegment(
                        index=len(merged) + 1,
                        start_ms=sentence.start_time,
                        end_ms=sentence.end_time,
                        text=sentence.text.strip(),
                        speaker=speaker or "default",
                    )
                )
                merged_speakers.append(speaker)
            group_start = group_end
    finally:
        splitter.stop()
    return merged, merged_speakers


def _load_pending_narrator_restores(source_subtitle: Path) -> set[int]:
    path = _narrator_review_path(source_subtitle)
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {int(index) for index in payload.get("restore_on_next_run", [])}
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return set()


def _save_narrator_review_artifacts(
    source_subtitle: Path,
    filtered_subtitle: Path,
    report: dict,
    dropped: list[dict],
    asr_data: ASRData,
) -> Path:
    """Persist the actual deleted rows so they can be reviewed after the run."""
    review_path = _narrator_review_path(source_subtitle)
    dropped_path = _narrator_dropped_path(source_subtitle)
    payload = {
        "source_subtitle": str(source_subtitle),
        "filtered_subtitle": str(filtered_subtitle),
        "report": report,
        "dropped": dropped,
    }
    review_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    selected = [
        asr_data.segments[item["index"]]
        for item in dropped
        if 0 <= int(item.get("index", -1)) < len(asr_data.segments)
    ]
    ASRData(selected).to_srt(save_path=str(dropped_path))
    return review_path


class VideoTranslationThread(QThread):
    """可暂停人工复核的单视频字幕处理线程。

    ``manual_review`` 仅控制被删除说话人字幕是否暂停等待 UI；
    ``translation_review`` 独立控制翻译表格复核。
    """

    progress = pyqtSignal(int, str)
    error = pyqtSignal(str)
    finished = pyqtSignal(str)
    narrator_review_required = pyqtSignal(object, object)
    narrator_review_saved = pyqtSignal(str)
    translation_ready = pyqtSignal(str, object)

    def __init__(
        self,
        video_path: str,
        *,
        manual_review: bool = False,
        translation_review: bool = True,
        subtitle_action: str | None = None,
    ):
        super().__init__()
        self.video_path = str(video_path)
        self.manual_review = manual_review
        self.translation_review = translation_review
        action = subtitle_action or str(cfg.subtitle_action.value or "translate")
        self.subtitle_action = action if action in {"translate", "rewrite"} else "translate"
        snapshot_task = TaskFactory.create_subtitle_task(
            self.video_path, self.video_path, need_next_task=False
        )
        self.subtitle_config = snapshot_task.subtitle_config
        if self.subtitle_config:
            self.subtitle_config.subtitle_action = self.subtitle_action
        self.translate_original_subtitles = bool(
            cfg.dubbing_translate_original_subtitles.value
        )
        self._cancelled = False
        self._narrator_event = threading.Event()
        self._translation_event = threading.Event()
        self._narrator_restore: list[int] = []
        self._translation_data: dict = {}
        self._speaker_source_intervals: list[tuple[int, int]] = []
        self._speaker_source_labels: list[str] = []
        self._narrator_speaker = ""
        self._protected_subtitle_path: Path | None = None
        self._display_subtitle_path: Path | None = None
        self._active_child = None

    def run(self):
        try:
            self._run_workflow()
        except Exception as exc:  # noqa: BLE001
            logger.exception("视频字幕处理流程失败: %s", exc)
            if not self._cancelled:
                self.error.emit(str(exc))

    def _run_workflow(self):
        video = Path(self.video_path)
        if not video.is_file():
            raise ValueError("视频文件不存在")
        output_dir = _job_output_dir(
            video,
            str(cfg.dubbing_output_dir.value or ""),
            self.subtitle_action,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        intermediate_dir = output_dir / "中间文件"
        intermediate_dir.mkdir(parents=True, exist_ok=True)

        self.progress.emit(0, "开始视频转录...")
        trans_task = TaskFactory.create_transcribe_task(self.video_path, need_next_task=True)
        trans_task.output_path = str(intermediate_dir / Path(trans_task.output_path).name)
        trans_result = self._run_child(
            TranscriptThread(trans_task), 0, 25, "视频转录"
        )
        if not isinstance(trans_result, TranscribeTask) or not trans_result.output_path:
            raise RuntimeError("转录未生成字幕文件")
        source_subtitle = Path(trans_result.output_path)
        if source_subtitle.parent.resolve() != intermediate_dir.resolve():
            local_subtitle = intermediate_dir / source_subtitle.name
            shutil.copy2(source_subtitle, local_subtitle)
            source_subtitle = local_subtitle

        if bool(cfg.dubbing_enable_diarization.value):
            source_subtitle = self._prepare_narrator_filter(
                source_subtitle,
                video,
                narrator_only=bool(cfg.dubbing_narrator_only.value),
            )
        if self._cancelled:
            return

        is_rewrite = self.subtitle_action == "rewrite"
        action_label = "洗稿" if is_rewrite else "翻译"
        self.progress.emit(25, f"开始字幕{action_label}...")
        subtitle_task = TaskFactory.create_subtitle_task(
            str(source_subtitle), self.video_path, need_next_task=False
        )
        subtitle_task.output_path = str(
            source_subtitle.with_name(
                source_subtitle.stem
                + ("-rewritten.srt" if is_rewrite else "-translated.srt")
            )
        )
        subtitle_task.subtitle_config = self.subtitle_config
        # 翻译表复核阶段保留双语字幕供表格对照；批量模式直接输出仅译文。
        if subtitle_task.subtitle_config:
            subtitle_task.subtitle_config.subtitle_layout = (
                SubtitleLayoutEnum.ORIGINAL_ON_TOP
                if self.translation_review
                else SubtitleLayoutEnum.ONLY_TRANSLATE
            )
        subtitle_thread = SubtitleThread(subtitle_task)
        subtitle_result = self._run_child(
            subtitle_thread, 25, 30, f"字幕{action_label}"
        )
        self._translation_data = subtitle_thread.result_data
        translated_path = Path(subtitle_result[1] if isinstance(subtitle_result, tuple) else subtitle_task.output_path)
        if not translated_path.exists():
            translated_path = Path(subtitle_task.output_path or source_subtitle)

        if self.translation_review:
            self.translation_ready.emit(str(translated_path), self._translation_data)
            self._wait_for_review(self._translation_event, f"{action_label}字幕")
            if self._cancelled:
                return

        _write_dubbing_subtitle(translated_path, self._translation_data)
        _write_dubbing_speaker_sidecar(
            translated_path,
            self._translation_data,
            self._speaker_source_intervals,
            self._speaker_source_labels,
            self._narrator_speaker,
        )

        if self._protected_subtitle_path is not None:
            self._display_subtitle_path = self._protected_subtitle_path
            if self.translate_original_subtitles:
                self._display_subtitle_path = self._translate_original_track(
                    self._protected_subtitle_path
                )

        self.progress.emit(60, "开始字幕配音与画面对齐...")
        config = TaskFactory.create_dubbing_config(include_alignment_audio=True)
        # 视频字幕处理必须按字幕时间轴对齐；配音面板的固定停顿模式会跳过视频变速。
        config.fixed_line_pause = False
        # 画面变速模式保留 TTS 自然语速，不再先做一轮音频加速。
        if config.video_autorate:
            config.fit_mode = "none"
        config.output_dir = str(output_dir)
        # 说话人识别和解说筛选已在翻译前完成，避免配音阶段重复识别整段视频。
        config.enable_diarization = False
        config.narrator_only = False
        config.narrator_llm_review = False
        dub_thread = DubbingInterfaceThread(
            input_mode="subtitle",
            input_data=str(translated_path),
            video_path=self.video_path,
            config_override=config,
            display_subtitle_path=(
                str(self._display_subtitle_path)
                if self._display_subtitle_path is not None
                else None
            ),
            protected_subtitle_path=(
                str(self._protected_subtitle_path)
                if self._protected_subtitle_path is not None
                else None
            ),
        )
        output = self._run_child(dub_thread, 60, 40, "配音与画面对齐")
        output_path = output[0] if isinstance(output, tuple) else output
        _organize_outputs(output_dir, video, translated_path)
        self.progress.emit(100, f"视频{action_label}完成")
        self.finished.emit(str(output_path))

    def _run_child(self, child, offset: int, scale: int, stage: str):
        state: dict[str, object] = {"result": None, "error": None}
        child.progress.connect(
            lambda value, message: self.progress.emit(
                offset + int(value * scale / 100), f"{stage}: {message}"
            )
        )
        child.error.connect(lambda message: state.update(error=message))
        child.finished.connect(lambda *args: state.update(result=args))
        self._active_child = child
        try:
            child.run()
        finally:
            if self._active_child is child:
                self._active_child = None
        if self._cancelled:
            raise RuntimeError("任务已取消")
        if state["error"]:
            raise RuntimeError(str(state["error"]))
        result = state["result"]
        if result is None:
            raise RuntimeError(f"{stage}未返回完成结果")
        if len(result) == 1:
            return result[0]
        return result

    def _prepare_narrator_filter(
        self, source_subtitle: Path, video: Path, *, narrator_only: bool
    ) -> Path:
        self.progress.emit(20, "正在识别说话人...")
        from videocaptioner.core.diarization import diarize
        from videocaptioner.core.diarization.assign import assign_speakers

        segments = load_dubbing_segments(str(source_subtitle), text_track="source")
        if not segments:
            return source_subtitle
        diarizations = diarize(
            str(video),
            num_speakers=int(cfg.dubbing_speaker_count.value or 0),
            language=diarization_language_from_transcribe(
                cfg.transcribe_language.value
            ),
            progress=lambda value, message: self.progress.emit(20 + value // 20, message),
            isolate_process=True,
            cancelled=lambda: self._cancelled,
        )
        speakers = assign_speakers(segments, diarizations)
        source_speakers = list(speakers)
        if narrator_only:
            segments, speakers = _merge_word_level_segments(
                segments,
                speakers,
                max_cjk=int(getattr(self.subtitle_config, "max_word_count_cjk", 25) or 25),
                max_words=int(
                    getattr(self.subtitle_config, "max_word_count_english", 18) or 18
                ),
            )
        for segment, speaker in zip(segments, speakers):
            segment.speaker = str(speaker or "").strip() or "default"
        self._speaker_source_intervals = [
            (segment.start_ms, segment.end_ms) for segment in segments
        ]
        self._speaker_source_labels = list(speakers)
        try:
            write_speaker_json(source_speakers, speaker_sidecar_path(source_subtitle))
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("说话人标签文件写入失败,已继续处理: %s", exc)
        kept, report = filter_narrator_subtitles(
            segments,
            speakers,
            keep_same_lang=False,
        )
        self._narrator_speaker = (
            str(report.get("narrator_speaker_id") or "").strip()
            if narrator_only
            else ""
        )
        dropped = report.get("dropped", [])
        llm_details: dict[int, dict] = {}

        if narrator_only and bool(cfg.dubbing_narrator_llm_review.value) and dropped:
            try:
                from videocaptioner.core.dubbing.narrator_llm_judge import judge_dropped

                kept_segments = [segments[i] for i in kept]
                dropped_segments = [segments[item["index"]] for item in dropped]
                dubbing_config = TaskFactory.create_dubbing_config()
                fields = (
                    dubbing_config.llm_api_key,
                    dubbing_config.llm_api_base,
                    dubbing_config.llm_model,
                )
                restored = judge_dropped(
                    kept_segments,
                    dropped_segments,
                    fields,
                    details_callback=llm_details.update,
                )
                for position, item in enumerate(dropped):
                    detail = llm_details.get(position, {})
                    item["llm_label"] = detail.get("label", "")
                    item["llm_reason"] = detail.get("reason", "")
                restored_indices = {
                    dropped[i]["index"]
                    for i in restored
                    if isinstance(i, int)
                    and not isinstance(i, bool)
                    and 0 <= i < len(dropped)
                }
                kept = sorted(set(kept) | restored_indices)
                if restored_indices:
                    dropped = [
                        item for item in dropped if item["index"] not in restored_indices
                    ]
                    report["dropped"] = dropped
                    report["dropped_count"] = len(dropped)
                report["llm_reviewed_count"] = len(llm_details)
                report["llm_restored_count"] = len(restored_indices)
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM 解说复核失败,保留人工复核: %s", exc)

        # ponytail: indices assume deterministic retranscription; match by
        # timestamp/text if users later need restores to survive changed ASR output.
        pending_restored = _load_pending_narrator_restores(source_subtitle) & {
            int(item["index"]) for item in dropped
        }
        if pending_restored:
            kept = sorted(set(kept) | pending_restored)
            dropped = [
                item for item in dropped if item["index"] not in pending_restored
            ]
            report["previous_manual_restored_count"] = len(pending_restored)
            report["dropped"] = dropped
            report["dropped_count"] = len(dropped)

        if narrator_only and self.manual_review and dropped:
            self._narrator_event.clear()
            self.narrator_review_required.emit(report, dropped)
            self._wait_for_review(self._narrator_event, "解说字幕")
            reviewable_indices = {int(item["index"]) for item in dropped}
            human_restored = {
                int(index)
                for index in self._narrator_restore
                if isinstance(index, int) and not isinstance(index, bool)
            } & reviewable_indices
            kept = sorted(set(kept) | human_restored)
            dropped = [
                item for item in dropped if item["index"] not in human_restored
            ]
            report["human_restored_count"] = len(human_restored)
            report["dropped"] = dropped
            report["dropped_count"] = len(dropped)

        report["kept_count"] = len(kept)

        if narrator_only and not kept:
            raise ValueError("说话人筛选后没有可用字幕，请在复核中恢复字幕")

        if not narrator_only:
            return source_subtitle

        asr_data = ASRData(
            [
                ASRDataSeg(segment.text, segment.start_ms, segment.end_ms)
                for segment in segments
            ]
        )
        selected = [asr_data.segments[i] for i in kept if i < len(asr_data.segments)]
        filtered_path = source_subtitle.with_name(source_subtitle.stem + "-narrator.srt")
        ASRData(selected).to_srt(save_path=str(filtered_path))
        review_path = _save_narrator_review_artifacts(
            source_subtitle, filtered_path, report, dropped, asr_data
        )
        self._protected_subtitle_path = _narrator_dropped_path(source_subtitle)
        self.narrator_review_saved.emit(str(review_path))
        return filtered_path

    def _translate_original_track(self, source_path: Path) -> Path:
        if not source_path.is_file() or not load_dubbing_segments(str(source_path)):
            return source_path
        subtitle_task = TaskFactory.create_subtitle_task(
            str(source_path), self.video_path, need_next_task=False
        )
        subtitle_task.output_path = str(
            source_path.with_name(source_path.stem + "-translated.srt")
        )
        subtitle_task.subtitle_config = copy.deepcopy(self.subtitle_config)
        if subtitle_task.subtitle_config is None:
            raise RuntimeError("原片字幕翻译配置不可用")
        subtitle_task.subtitle_config.subtitle_action = "translate"
        subtitle_task.subtitle_config.need_translate = True
        subtitle_task.subtitle_config.need_optimize = False
        subtitle_task.subtitle_config.subtitle_layout = SubtitleLayoutEnum.ONLY_TRANSLATE
        subtitle_thread = SubtitleThread(subtitle_task)
        result = self._run_child(subtitle_thread, 55, 5, "原片字幕翻译")
        translated_path = Path(
            result[1] if isinstance(result, tuple) else subtitle_task.output_path
        )
        if subtitle_thread.result_data:
            _write_dubbing_subtitle(translated_path, subtitle_thread.result_data)
        if not translated_path.is_file():
            raise RuntimeError("原片字幕翻译未生成字幕文件")
        return translated_path

    @staticmethod
    def _wait_for_review(event: threading.Event, stage: str) -> None:
        if not event.wait(REVIEW_WAIT_TIMEOUT_SECONDS):
            logger.warning("%s复核等待超时，自动继续", stage)

    def continue_narrator_review(self, restore_indices: list[int]):
        self._narrator_restore = list(restore_indices or [])
        self._narrator_event.set()

    def continue_translation(self, subtitle_data: dict | None = None):
        if subtitle_data is not None:
            self._translation_data = subtitle_data
        self._translation_event.set()

    def cancel(self):
        self._cancelled = True
        self._narrator_event.set()
        self._translation_event.set()
        child = self._active_child
        if child is not None:
            child.requestInterruption()
            stopper = getattr(child, "cancel", None) or getattr(child, "stop", None)
            if callable(stopper):
                stopper()
