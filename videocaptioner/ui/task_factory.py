import datetime
from pathlib import Path
from typing import Optional

from videocaptioner.config import MODEL_PATH
from videocaptioner.core.dubbing import DubbingConfig
from videocaptioner.core.entities import (
    LANGUAGES,
    FullProcessTask,
    LLMServiceEnum,
    SubtitleConfig,
    SubtitleTask,
    SynthesisConfig,
    SynthesisTask,
    TranscribeConfig,
    TranscribeTask,
    TranscriptAndSubtitleTask,
)
from videocaptioner.core.llm.client import resolve_llm_base_url
from videocaptioner.ui.common.config import Config, cfg
from videocaptioner.ui.dubbing_config_builder import create_dubbing_config_from_cfg
from videocaptioner.ui.dubbing_config_builder import (
    resolve_dubbing_voice as resolve_dubbing_voice,
)


class TaskFactory:
    """任务工厂类，用于创建各种类型的任务"""

    @staticmethod
    def get_ass_style(style_name: str) -> str:
        """获取 ASS 字幕样式内容 (via style_manager, JSON-first with .txt fallback)"""
        from videocaptioner.core.subtitle.style_manager import load_style

        style = load_style(style_name)
        if style is not None:
            return style.to_ass_string()
        return ""

    @staticmethod
    def get_rounded_style(cfg_source: Optional[Config] = None) -> dict:
        """获取圆角背景样式配置 (from UI cfg overrides)"""
        cfg_src = cfg_source or cfg
        return {
            "font_name": cfg_src.rounded_bg_font_name.value,
            "font_size": cfg_src.rounded_bg_font_size.value,
            "bg_color": cfg_src.rounded_bg_color.value,
            "text_color": cfg_src.rounded_bg_text_color.value,
            "corner_radius": cfg_src.rounded_bg_corner_radius.value,
            "padding_h": cfg_src.rounded_bg_padding_h.value,
            "padding_v": cfg_src.rounded_bg_padding_v.value,
            "margin_bottom": cfg_src.rounded_bg_margin_bottom.value,
            "line_spacing": cfg_src.rounded_bg_line_spacing.value,
            "letter_spacing": cfg_src.rounded_bg_letter_spacing.value,
        }

    @staticmethod
    def create_transcribe_task(
        file_path: str,
        need_next_task: bool = False,
        task_id: Optional[str] = None,
        need_word_time_stamp: Optional[bool] = None,
        cfg_source: Optional[Config] = None,
    ) -> TranscribeTask:
        """创建转录任务

        Args:
            file_path: 视频/音频文件路径
            need_next_task: 是否为后续任务(字幕/对齐)转写
            task_id: 任务 ID
            need_word_time_stamp: 词级时间戳开关。None 时按默认语义取
                cfg.need_split(供字幕智能断句使用);视频对齐面板等独立流程
                可显式传入自己的开关,避免与字幕面板设置互相影响。
            cfg_source: 配置来源；批量任务传 ConfigSnapshot 固定入队时的
                设置，默认 None 使用全局 cfg（实时值）。
        """
        # 获取文件名
        file_name = Path(file_path).stem
        cfg_src = cfg_source or cfg

        # 构建输出路径
        if need_next_task:
            if need_word_time_stamp is None:
                need_word_time_stamp = cfg_src.need_split.value
            output_path = str(
                Path(cfg_src.work_dir.value)
                / file_name
                / "subtitle"
                / f"【原始字幕】{file_name}-{cfg_src.transcribe_model.value.value}-{cfg_src.transcribe_language.value.value}.srt"
            )
        else:
            need_word_time_stamp = False
            output_path = str(Path(file_path).parent / f"{file_name}.srt")

        config = TranscribeConfig(
            transcribe_model=cfg_src.transcribe_model.value,
            transcribe_language=LANGUAGES[cfg_src.transcribe_language.value.value],
            need_word_time_stamp=need_word_time_stamp,
            output_format=cfg_src.transcribe_output_format.value,
            # Whisper Cpp 配置
            whisper_model=cfg_src.whisper_model.value,
            # Whisper API 配置
            whisper_api_key=cfg_src.whisper_api_key.value,
            whisper_api_base=cfg_src.whisper_api_base.value,
            whisper_api_model=cfg_src.whisper_api_model.value,
            whisper_api_prompt=cfg_src.whisper_api_prompt.value,
            # Faster Whisper 配置
            faster_whisper_program=cfg_src.faster_whisper_program.value,
            faster_whisper_model=cfg_src.faster_whisper_model.value,
            faster_whisper_model_dir=str(MODEL_PATH),
            faster_whisper_device=cfg_src.faster_whisper_device.value,
            faster_whisper_vad_filter=cfg_src.faster_whisper_vad_filter.value,
            faster_whisper_vad_threshold=cfg_src.faster_whisper_vad_threshold.value,
            faster_whisper_vad_method=cfg_src.faster_whisper_vad_method.value,
            faster_whisper_ff_mdx_kim2=cfg_src.faster_whisper_ff_mdx_kim2.value,
            faster_whisper_one_word=cfg_src.faster_whisper_one_word.value,
            faster_whisper_prompt=cfg_src.faster_whisper_prompt.value,
        )

        task = TranscribeTask(
            queued_at=datetime.datetime.now(),
            file_path=file_path,
            output_path=output_path,
            transcribe_config=config,
            need_next_task=need_next_task,
        )
        if task_id:
            task.task_id = task_id
        return task

    @staticmethod
    def create_subtitle_task(
        file_path: str,
        video_path: Optional[str] = None,
        need_next_task: bool = False,
        task_id: Optional[str] = None,
        cfg_source: Optional[Config] = None,
    ) -> SubtitleTask:
        """创建字幕任务

        Args:
            cfg_source: 配置来源；批量任务传 ConfigSnapshot 固定入队时的
                设置，默认 None 使用全局 cfg（实时值）。
        """
        cfg_src = cfg_source or cfg
        output_name = (
            Path(file_path).stem.replace("【原始字幕】", "").replace("【下载字幕】", "")
        )
        # 只在需要翻译或洗稿时添加处理后缀
        suffix = (
            (
                "-LLM 大模型洗稿"
                if cfg_src.subtitle_action.value == "rewrite"
                else f"-{cfg_src.translator_service.value.value}"
            )
            if cfg_src.need_translate.value
            else ""
        )

        if need_next_task:
            output_path = str(
                Path(file_path).parent / f"【样式字幕】{output_name}{suffix}.ass"
            )
        else:
            output_path = str(
                Path(file_path).parent / f"【字幕】{output_name}{suffix}.srt"
            )

        # 根据当前选择的LLM服务获取对应的配置
        current_service = cfg_src.llm_service.value
        if current_service == LLMServiceEnum.OPENAI:
            base_url = cfg_src.openai_api_base.value
            api_key = cfg_src.openai_api_key.value
            llm_model = cfg_src.openai_model.value
        elif current_service == LLMServiceEnum.SILICON_CLOUD:
            base_url = cfg_src.silicon_cloud_api_base.value
            api_key = cfg_src.silicon_cloud_api_key.value
            llm_model = cfg_src.silicon_cloud_model.value
        elif current_service == LLMServiceEnum.DEEPSEEK:
            base_url = cfg_src.deepseek_api_base.value
            api_key = cfg_src.deepseek_api_key.value
            llm_model = cfg_src.deepseek_model.value
        elif current_service == LLMServiceEnum.OLLAMA:
            base_url = cfg_src.ollama_api_base.value
            api_key = cfg_src.ollama_api_key.value
            llm_model = cfg_src.ollama_model.value
        elif current_service == LLMServiceEnum.LM_STUDIO:
            base_url = cfg_src.lm_studio_api_base.value
            api_key = cfg_src.lm_studio_api_key.value
            llm_model = cfg_src.lm_studio_model.value
        elif current_service == LLMServiceEnum.GEMINI:
            base_url = cfg_src.gemini_api_base.value
            api_key = cfg_src.gemini_api_key.value
            llm_model = cfg_src.gemini_model.value
        elif current_service == LLMServiceEnum.CHATGLM:
            base_url = cfg_src.chatglm_api_base.value
            api_key = cfg_src.chatglm_api_key.value
            llm_model = cfg_src.chatglm_model.value
        elif current_service == LLMServiceEnum.ANTHROPIC:
            base_url = cfg_src.anthropic_api_base.value
            api_key = cfg_src.anthropic_api_key.value
            llm_model = cfg_src.anthropic_model.value
        else:
            base_url = ""
            api_key = ""
            llm_model = ""

        base_url = resolve_llm_base_url(base_url)

        config = SubtitleConfig(
            # 翻译配置
            base_url=base_url,
            api_key=api_key,
            llm_model=llm_model,
            deeplx_endpoint=cfg_src.deeplx_endpoint.value,
            # 翻译服务
            translator_service=cfg_src.translator_service.value,
            # 字幕处理
            need_reflect=cfg_src.need_reflect_translate.value,
            need_translate=cfg_src.need_translate.value,
            need_optimize=cfg_src.need_optimize.value,
            thread_num=cfg_src.thread_num.value,
            batch_size=cfg_src.batch_size.value,
            translation_mode=cfg_src.translation_mode.value,
            subtitle_action=cfg_src.subtitle_action.value,
            # 字幕布局、样式
            subtitle_layout=cfg_src.subtitle_layout.value,  # Now returns SubtitleLayoutEnum
            subtitle_style=TaskFactory.get_ass_style(cfg_src.subtitle_style_name.value),
            # 字幕分割
            max_word_count_cjk=cfg_src.max_word_count_cjk.value,
            max_word_count_english=cfg_src.max_word_count_english.value,
            need_split=cfg_src.need_split.value,
            # 字幕翻译
            target_language=cfg_src.target_language.value,
            # 字幕提示
            translation_prompt_text=cfg_src.translation_prompt_text.value,
            rewrite_prompt_text=cfg_src.rewrite_prompt_text.value,
            custom_prompt_text=cfg_src.custom_prompt_text.value,
        )

        task = SubtitleTask(
            queued_at=datetime.datetime.now(),
            subtitle_path=file_path,
            video_path=video_path,
            output_path=output_path,
            subtitle_config=config,
            need_next_task=need_next_task,
        )
        if task_id:
            task.task_id = task_id
        return task

    @staticmethod
    def create_synthesis_task(
        video_path: str,
        subtitle_path: str,
        need_next_task: bool = False,
        task_id: Optional[str] = None,
        cfg_source: Optional[Config] = None,
    ) -> SynthesisTask:
        """创建视频合成任务

        Args:
            cfg_source: 配置来源；批量任务传 ConfigSnapshot 固定入队时的
                设置，默认 None 使用全局 cfg（实时值）。
        """
        cfg_src = cfg_source or cfg
        output_path = str(
            Path(video_path).parent / f"【卡卡】{Path(video_path).stem}.mp4"
        )

        # 只有启用样式时才传入样式配置
        use_style = cfg_src.use_subtitle_style.value
        config = SynthesisConfig(
            need_video=cfg_src.need_video.value,
            soft_subtitle=cfg_src.soft_subtitle.value,
            render_mode=cfg_src.subtitle_render_mode.value,
            video_quality=cfg_src.video_quality.value,
            subtitle_layout=cfg_src.subtitle_layout.value,
            ass_style=TaskFactory.get_ass_style(cfg_src.subtitle_style_name.value) if use_style else "",
            rounded_style=TaskFactory.get_rounded_style(cfg_source) if use_style else None,
        )

        task = SynthesisTask(
            queued_at=datetime.datetime.now(),
            video_path=video_path,
            subtitle_path=subtitle_path,
            output_path=output_path,
            synthesis_config=config,
            need_next_task=need_next_task,
        )
        if task_id:
            task.task_id = task_id
        return task

    @staticmethod
    def create_transcript_and_subtitle_task(
        file_path: str,
        output_path: Optional[str] = None,
        transcribe_config: Optional[TranscribeConfig] = None,
        subtitle_config: Optional[SubtitleConfig] = None,
    ) -> TranscriptAndSubtitleTask:
        """创建转录和字幕任务"""
        if output_path is None:
            output_path = str(
                Path(file_path).parent / f"{Path(file_path).stem}_processed.srt"
            )

        return TranscriptAndSubtitleTask(
            queued_at=datetime.datetime.now(),
            file_path=file_path,
            output_path=output_path,
        )

    @staticmethod
    def create_full_process_task(
        file_path: str,
        output_path: Optional[str] = None,
        transcribe_config: Optional[TranscribeConfig] = None,
        subtitle_config: Optional[SubtitleConfig] = None,
        synthesis_config: Optional[SynthesisConfig] = None,
    ) -> FullProcessTask:
        """创建完整处理任务（转录+字幕+合成）"""
        if output_path is None:
            output_path = str(
                Path(file_path).parent
                / f"{Path(file_path).stem}_final{Path(file_path).suffix}"
            )

        return FullProcessTask(
            queued_at=datetime.datetime.now(),
            file_path=file_path,
            output_path=output_path,
        )

    @staticmethod
    def create_dubbing_config(
        include_alignment_audio: bool = False,
        cfg_source: Optional[Config] = None,
    ) -> DubbingConfig:
        """从配音面板全局 cfg 创建配置（与 CLI dub 命令字段对齐）。

        Args:
            cfg_source: 配置来源；批量任务传 ConfigSnapshot 固定入队时的
                设置，默认 None 使用全局 cfg（实时值）。
        """
        return create_dubbing_config_from_cfg(
            include_alignment_audio=include_alignment_audio,
            cfg_source=cfg_source,
        )

