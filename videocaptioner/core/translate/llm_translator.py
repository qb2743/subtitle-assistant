"""LLM translator using an OpenAI-compatible API."""

import hashlib
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import json_repair
import openai

from videocaptioner.core.asr.asr_data import ASRData
from videocaptioner.core.llm import call_llm
from videocaptioner.core.prompts import get_prompt
from videocaptioner.core.translate.base import BaseTranslator, SubtitleProcessData, logger
from videocaptioner.core.translate.types import TargetLanguage
from videocaptioner.core.utils.cache import generate_cache_key, is_cache_enabled


class LLMTranslator(BaseTranslator):
    """LLM translator for OpenAI-compatible APIs."""

    MAX_STEPS = 3
    STRUCTURED_TEMPERATURE = 0.1
    ERROR_MARKERS = {"ERROR", "TRANSLATION_ERROR", "FAILED"}

    def __init__(
        self,
        thread_num: int,
        batch_num: int,
        target_language: TargetLanguage,
        model: str,
        custom_prompt: str,
        is_reflect: bool,
        update_callback: Optional[Callable],
    ):
        super().__init__(
            thread_num=thread_num,
            batch_num=batch_num,
            target_language=target_language,
            update_callback=update_callback,
        )

        self.model = model
        self.custom_prompt = custom_prompt
        self.is_reflect = is_reflect

    def translate_subtitle(self, subtitle_data: ASRData) -> ASRData:
        """Translate a subtitle with full context while preserving local timestamps.

        The model receives the whole subtitle as an index-to-text JSON object. It
        never receives timestamps, so translated text is mapped back to the
        original ASRData segments by index and timing stays local.
        """
        try:
            translate_data_list = [
                SubtitleProcessData(index=i, original_text=seg.text)
                for i, seg in enumerate(subtitle_data.segments, 1)
            ]

            try:
                translated_list = self._safe_translate_full_context(translate_data_list)
            except Exception as e:
                logger.warning(
                    f"Full-context LLM translation failed; falling back to chunked mode: {e}"
                )
                chunks = self._split_chunks(translate_data_list)
                translated_list = self._parallel_translate(chunks)
                self._repair_failed_translations(translated_list)

            new_segments = self._set_segments_translated_text(
                subtitle_data.segments, translated_list
            )
            return ASRData(new_segments)
        except Exception as e:
            logger.error(f"Translation failed: {str(e)}")
            raise RuntimeError(f"Translation failed: {str(e)}")

    def _translate_chunk(
        self, subtitle_chunk: List[SubtitleProcessData]
    ) -> List[SubtitleProcessData]:
        """Translate one chunk. Used as fallback when full-context mode fails."""
        if not subtitle_chunk:
            return subtitle_chunk

        logger.debug(
            f"[+] Translating subtitle chunk: {subtitle_chunk[0].index} - {subtitle_chunk[-1].index}"
        )
        subtitle_dict = {str(data.index): data.original_text for data in subtitle_chunk}
        prompt = self._get_translation_prompt()

        try:
            result_dict = self._agent_loop(
                prompt,
                subtitle_dict,
                temperature=self.STRUCTURED_TEMPERATURE,
            )
            processed_result = self._normalize_result_dict(result_dict)

            for data in subtitle_chunk:
                data.translated_text = processed_result.get(str(data.index), "")
            self._repair_failed_translations(subtitle_chunk)
            return subtitle_chunk
        except openai.RateLimitError as e:
            logger.error(f"OpenAI Rate Limit Error: {str(e)}")
            raise
        except openai.AuthenticationError as e:
            logger.error(f"OpenAI Authentication Error: {str(e)}")
            raise
        except openai.NotFoundError as e:
            logger.error(f"OpenAI NotFound Error: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"LLM translation error: {e}")
            return self._translate_chunk_single(subtitle_chunk)

    def _safe_translate_full_context(
        self, subtitle_data: List[SubtitleProcessData]
    ) -> List[SubtitleProcessData]:
        """Translate all rows in one request and repair suspicious rows."""
        cache_key = self._get_full_context_cache_key(subtitle_data)
        if is_cache_enabled():
            try:
                cached_result = self._cache.get(cache_key, default=None)
            except Exception:
                cached_result = None
                self._cache.delete(cache_key)
            if cached_result is not None:
                if self._is_cacheable_result(cached_result):
                    return cached_result
                logger.warning(f"Ignoring invalid LLM translation cache: {cache_key}")
                self._cache.delete(cache_key)

        result = self._translate_full_context(subtitle_data)
        self._repair_failed_translations(result)

        if self.update_callback:
            self.update_callback(result)

        if is_cache_enabled():
            if self._is_cacheable_result(result):
                self._cache.set(cache_key, result, expire=86400 * 7)
            else:
                logger.warning(
                    f"Skipping LLM translation cache write for invalid result: {cache_key}"
                )
        return result

    def _translate_full_context(
        self, subtitle_data: List[SubtitleProcessData]
    ) -> List[SubtitleProcessData]:
        """Translate the complete subtitle as index->text JSON without timestamps."""
        if not subtitle_data:
            return subtitle_data

        logger.debug(
            f"[+] Full-context LLM translation: {subtitle_data[0].index} - {subtitle_data[-1].index}"
        )
        subtitle_dict = {str(data.index): data.original_text for data in subtitle_data}
        prompt = self._get_full_context_prompt()
        result_dict = self._agent_loop(
            prompt,
            subtitle_dict,
            temperature=self.STRUCTURED_TEMPERATURE,
        )
        processed_result = self._normalize_result_dict(result_dict)

        for data in subtitle_data:
            data.translated_text = processed_result.get(str(data.index), "")

        return subtitle_data

    def _get_translation_prompt(self) -> str:
        if self.is_reflect:
            return get_prompt(
                "translate/reflect",
                target_language=self.target_language,
                custom_prompt=self.custom_prompt,
            )
        return get_prompt(
            "translate/standard",
            target_language=self.target_language,
            custom_prompt=self.custom_prompt,
        )

    def _get_full_context_prompt(self) -> str:
        prompt = self._get_translation_prompt()
        return (
            f"{prompt}\n\n"
            "<full_context_mode>\n"
            "The user message contains the complete subtitle as a JSON dictionary.\n"
            "Keys are immutable subtitle indexes. Values are subtitle text only; timestamps are intentionally omitted.\n"
            "Use the complete JSON as context for consistent terminology, names, pronouns, and style.\n"
            "Return ONLY a valid JSON dictionary with exactly the same keys. Do not add, remove, merge, split, or renumber keys.\n"
            "If a subtitle is a fragment, translate only that fragment while using surrounding entries for context.\n"
            "</full_context_mode>"
        )

    def _normalize_result_dict(self, result_dict: Any) -> Dict[str, str]:
        if not isinstance(result_dict, dict):
            return {}

        if self.is_reflect:
            return {
                key: f"{value.get('native_translation', value) if isinstance(value, dict) else value}"
                for key, value in result_dict.items()
            }
        return {key: f"{value}" for key, value in result_dict.items()}

    def _agent_loop(
        self,
        system_prompt: str,
        subtitle_dict: Dict[str, str],
        temperature: float = STRUCTURED_TEMPERATURE,
    ) -> Dict[str, str]:
        """Translate with validation feedback for malformed model responses."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(subtitle_dict, ensure_ascii=False)},
        ]
        last_response_dict = None

        for _ in range(self.MAX_STEPS):
            response = call_llm(
                messages=messages,
                model=self.model,
                temperature=temperature,
            )
            response_dict = json_repair.loads(
                response.choices[0].message.content.strip()
            )
            last_response_dict = response_dict
            is_valid, error_message = self._validate_llm_response(
                response_dict, subtitle_dict
            )
            if is_valid:
                return response_dict

            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(response_dict, ensure_ascii=False),
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Error: {error_message}\n\n"
                        f"Fix the errors above and output ONLY a valid JSON dictionary "
                        f"with ALL {len(subtitle_dict)} keys"
                    ),
                }
            )

        return last_response_dict or {}

    def _validate_llm_response(
        self, response_dict: Any, subtitle_dict: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Validate LLM JSON output for standard and reflect translation."""
        if not isinstance(response_dict, dict):
            return (
                False,
                f"Output must be a dict, got {type(response_dict).__name__}. Use format: {{'0': 'text', '1': 'text'}}",
            )

        expected_keys = set(subtitle_dict.keys())
        actual_keys = set(response_dict.keys())

        def sort_keys(keys):
            return sorted(keys, key=lambda x: int(x) if x.isdigit() else x)

        if expected_keys != actual_keys:
            missing = expected_keys - actual_keys
            extra = actual_keys - expected_keys
            error_parts = []

            if missing:
                error_parts.append(
                    f"Missing keys {sort_keys(missing)} - you must translate these items"
                )
            if extra:
                error_parts.append(
                    f"Extra keys {sort_keys(extra)} - these keys are not in input, remove them"
                )

            return (False, "; ".join(error_parts))

        if self.is_reflect:
            for key, value in response_dict.items():
                if not isinstance(value, dict):
                    return (
                        False,
                        f"Key '{key}': value must be a dict with 'native_translation' field. Got {type(value).__name__}.",
                    )

                if "native_translation" not in value:
                    available_keys = list(value.keys())
                    return (
                        False,
                        f"Key '{key}': missing 'native_translation' field. Found keys: {available_keys}. Must include 'native_translation'.",
                    )

        return True, ""

    def _translate_chunk_single(
        self, subtitle_chunk: List[SubtitleProcessData]
    ) -> List[SubtitleProcessData]:
        """Translate rows one by one as a repair path."""
        single_prompt = get_prompt(
            "translate/single", target_language=self.target_language
        )

        for data in subtitle_chunk:
            try:
                response = call_llm(
                    messages=[
                        {"role": "system", "content": single_prompt},
                        {"role": "user", "content": data.original_text},
                    ],
                    model=self.model,
                    temperature=self.STRUCTURED_TEMPERATURE,
                )
                data.translated_text = response.choices[0].message.content.strip()
            except Exception as e:
                logger.error(f"Single item translation failed {data.index}: {str(e)}")

        return subtitle_chunk

    def _repair_failed_translations(
        self, translated_list: List[SubtitleProcessData]
    ) -> None:
        """Retry rows that are empty, ERROR-like, or probably still source text."""
        failed_items = [
            data for data in translated_list if self._needs_retranslation(data)
        ]
        if not failed_items:
            return

        logger.warning(
            "Retrying failed or suspicious translations: "
            + ", ".join(str(data.index) for data in failed_items)
        )
        self._translate_chunk_single(failed_items)

        still_failed = [
            data for data in failed_items if self._needs_retranslation(data)
        ]
        if still_failed:
            logger.warning(
                "Some translations are still suspicious after retry: "
                + ", ".join(str(data.index) for data in still_failed)
            )

    def _needs_retranslation(self, data: SubtitleProcessData) -> bool:
        translated = (data.translated_text or "").strip()
        original = (data.original_text or "").strip()
        if not original:
            return False
        if not translated:
            return True

        if translated.upper() in self.ERROR_MARKERS:
            return True
        if "||ERROR" in translated:
            return True

        if self.target_language not in {
            TargetLanguage.ENGLISH,
            TargetLanguage.ENGLISH_US,
            TargetLanguage.ENGLISH_UK,
        } and self._normalize_for_compare(original) == self._normalize_for_compare(
            translated
        ):
            return self._has_translatable_content(original)

        return False

    @staticmethod
    def _normalize_for_compare(text: str) -> str:
        return re.sub(r"\s+", "", text).strip().lower()

    @staticmethod
    def _has_translatable_content(text: str) -> bool:
        return bool(re.search(r"[A-Za-z\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))

    def _get_cache_key(self, chunk: List[SubtitleProcessData]) -> str:
        """Generate chunk cache key."""
        class_name = self.__class__.__name__
        chunk_key = generate_cache_key(chunk)
        lang = self.target_language.value
        model = self.model
        return f"{class_name}:chunk:{chunk_key}:{lang}:{model}"

    def _get_full_context_cache_key(self, chunk: List[SubtitleProcessData]) -> str:
        """Generate full-context cache key."""
        class_name = self.__class__.__name__
        chunk_key = generate_cache_key(chunk)
        lang = self.target_language.value
        model = self.model
        prompt_mode = "reflect" if self.is_reflect else "standard"
        prompt_hash = hashlib.sha256(self.custom_prompt.encode()).hexdigest()
        return f"{class_name}:full-context-index-json:{prompt_mode}:{prompt_hash}:{chunk_key}:{lang}:{model}"
