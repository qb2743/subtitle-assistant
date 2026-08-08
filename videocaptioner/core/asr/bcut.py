import json
import time
from typing import Any, Callable, List, Optional, Union

import requests

from videocaptioner.core.utils.logger import setup_logger

from .asr_data import ASRDataSeg
from .base import BaseASR
from .status import ASRStatus

__version__ = "0.0.3"

API_BASE_URL = "https://member.bilibili.com/x/bcut/rubick-interface"
API_REQ_UPLOAD = API_BASE_URL + "/resource/create"
API_COMMIT_UPLOAD = API_BASE_URL + "/resource/create/complete"
API_CREATE_TASK = API_BASE_URL + "/task"
API_QUERY_RESULT = API_BASE_URL + "/task/result"
BCUT_RESOURCE_MODEL_ID = "8"
# The live API rejects task creation with 7, but result queries use 7.
BCUT_QUERY_MODEL_ID = 7
RESULT_REQUEST_ATTEMPTS = 3
RESULT_TASK_NOT_FOUND_ATTEMPTS = 4
RESULT_REQUEST_TIMEOUT = (5, 20)

logger = setup_logger("bcut")


class _BcutResponseError(RuntimeError):
    def __init__(self, operation: str, message: str, *, code: Any = None):
        self.code = code
        code_text = f" (code={code})" if code is not None else ""
        super().__init__(f"B 接口{operation}失败{code_text}: {message}")


def _response_data(
    response: requests.Response,
    operation: str,
    *,
    required_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise _BcutResponseError(operation, "返回的不是有效 JSON") from exc

    if not isinstance(payload, dict):
        raise _BcutResponseError(operation, "返回的数据格式无效")

    code = payload.get("code")
    if code not in (None, 0, "0"):
        message = payload.get("message") or payload.get("msg") or "未知业务错误"
        raise _BcutResponseError(operation, str(message), code=code)

    data = payload.get("data")
    if not isinstance(data, dict):
        message = payload.get("message") or payload.get("msg")
        if not message or str(message) == "0":
            message = "响应缺少 data"
        raise _BcutResponseError(operation, str(message), code=payload.get("code"))

    missing = [field for field in required_fields if field not in data]
    if missing:
        raise _BcutResponseError(
            operation,
            f"响应缺少字段: {', '.join(missing)}",
            code=payload.get("code"),
        )
    return data


class BcutASR(BaseASR):
    """Bilibili Bcut ASR API implementation.

    Uses Bilibili's cloud ASR service with multipart upload support.
    """

    headers = {
        "User-Agent": "Bilibili/1.0.0 (https://www.bilibili.com)",
        "Content-Type": "application/json",
    }

    def __init__(
        self,
        audio_input: Union[str, bytes],
        use_cache: bool = True,
        need_word_time_stamp: bool = False,
    ):
        super().__init__(audio_input, use_cache=use_cache)
        self.session = requests.Session()
        self.task_id: Optional[str] = None
        self.__etags: List[str] = []

        self.__in_boss_key: Optional[str] = None
        self.__resource_id: Optional[str] = None
        self.__upload_id: Optional[str] = None
        self.__upload_urls: List[str] = []
        self.__per_size: Optional[int] = None
        self.__clips: Optional[int] = None

        self.__etags_final: Optional[List[str]] = []
        self.__download_url: Optional[str] = None

        self.need_word_time_stamp = need_word_time_stamp

    def upload(self) -> None:
        """Request upload authorization and upload audio file."""
        if not self.file_binary:
            raise ValueError("No audio data to upload")
        payload = json.dumps(
            {
                "type": 2,
                "name": "audio.mp3",
                "size": len(self.file_binary),
                "ResourceFileType": "mp3",
                "model_id": BCUT_RESOURCE_MODEL_ID,
            }
        )

        resp = requests.post(API_REQ_UPLOAD, data=payload, headers=self.headers)
        resp_data = _response_data(
            resp,
            "请求上传",
            required_fields=(
                "in_boss_key",
                "resource_id",
                "upload_id",
                "upload_urls",
                "per_size",
            ),
        )

        self.__in_boss_key = resp_data["in_boss_key"]
        self.__resource_id = resp_data["resource_id"]
        self.__upload_id = resp_data["upload_id"]
        self.__upload_urls = resp_data["upload_urls"]
        self.__per_size = resp_data["per_size"]
        self.__clips = len(resp_data["upload_urls"])

        self.__upload_part()
        self.__commit_upload()

    def __upload_part(self) -> None:
        """Upload audio data in multiple parts."""
        if (
            self.__clips is None
            or self.__per_size is None
            or self.__upload_urls is None
            or self.file_binary is None
        ):
            raise ValueError("Upload parameters not initialized")

        for clip in range(self.__clips):
            start_range = clip * self.__per_size
            end_range = (clip + 1) * self.__per_size
            resp = requests.put(
                self.__upload_urls[clip],
                data=self.file_binary[start_range:end_range],
                headers=self.headers,
            )
            resp.raise_for_status()
            etag = resp.headers.get("Etag")
            if etag is not None:
                self.__etags.append(etag)

    def __commit_upload(self) -> None:
        """Commit the upload and get download URL."""
        data = json.dumps(
            {
                "InBossKey": self.__in_boss_key,
                "ResourceId": self.__resource_id,
                "Etags": ",".join(self.__etags) if self.__etags else "",
                "UploadId": self.__upload_id,
                "model_id": BCUT_RESOURCE_MODEL_ID,
            }
        )
        resp = requests.post(API_COMMIT_UPLOAD, data=data, headers=self.headers)
        resp_data = _response_data(
            resp, "确认上传", required_fields=("download_url",)
        )
        self.__download_url = resp_data["download_url"]

    def create_task(self) -> str:
        """Create ASR task."""
        resp = requests.post(
            API_CREATE_TASK,
            json={
                "resource": self.__download_url,
                "model_id": BCUT_RESOURCE_MODEL_ID,
            },
            headers=self.headers,
        )
        resp_data = _response_data(
            resp, "创建转录任务", required_fields=("task_id",)
        )
        self.task_id = resp_data["task_id"]
        return self.task_id or ""

    def result(self, task_id: Optional[str] = None):
        """Query ASR result."""
        network_failures = 0
        task_not_found_failures = 0
        while True:
            try:
                resp = requests.get(
                    API_QUERY_RESULT,
                    params={
                        "model_id": BCUT_QUERY_MODEL_ID,
                        "task_id": task_id or self.task_id,
                    },
                    headers=self.headers,
                    timeout=RESULT_REQUEST_TIMEOUT,
                )
                return _response_data(
                    resp, "查询转录结果", required_fields=("state",)
                )
            except requests.exceptions.HTTPError:
                raise
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as exc:
                network_failures += 1
                if network_failures >= RESULT_REQUEST_ATTEMPTS:
                    raise
                delay = 2 ** (network_failures - 1)
                logger.warning(
                    "Bcut result request failed (%s/%s), retrying in %ss: %s",
                    network_failures,
                    RESULT_REQUEST_ATTEMPTS,
                    delay,
                    exc,
                )
                time.sleep(delay)
            except _BcutResponseError as exc:
                if str(exc.code) != "9":
                    raise
                task_not_found_failures += 1
                if task_not_found_failures >= RESULT_TASK_NOT_FOUND_ATTEMPTS:
                    raise
                delay = 2 ** (task_not_found_failures - 1)
                logger.warning(
                    "Bcut task is not visible yet (%s/%s), retrying in %ss: %s",
                    task_not_found_failures,
                    RESULT_TASK_NOT_FOUND_ATTEMPTS,
                    delay,
                    exc,
                )
                time.sleep(delay)

    def _run(
        self, callback: Optional[Callable[[int, str], None]] = None, **kwargs: Any
    ) -> dict:
        """Execute ASR workflow: upload -> create task -> poll result."""

        self._check_rate_limit()

        def _default_callback(x, y):
            pass

        if callback is None:
            callback = _default_callback

        callback(*ASRStatus.UPLOADING.callback_tuple())
        self.upload()

        callback(*ASRStatus.CREATING_TASK.callback_tuple())
        self.create_task()

        callback(*ASRStatus.TRANSCRIBING.callback_tuple())

        # Poll task status until complete
        task_resp = None
        for _ in range(500):
            task_resp = self.result()
            state = task_resp["state"]
            if state == 4:
                break
            if state == 3:
                detail = task_resp.get("remark") or task_resp.get("message")
                raise RuntimeError(f"B 接口转录任务失败: {detail or '未知原因'}")
            if state not in (0, 1, 2):
                raise RuntimeError(f"B 接口返回未知任务状态: {state!r}")
            time.sleep(1)

        if task_resp is None or task_resp["state"] != 4:
            raise RuntimeError("ASR task failed or timeout")

        result_payload = task_resp.get("result")
        if isinstance(result_payload, str):
            result_payload = json.loads(result_payload)
        if not isinstance(result_payload, dict):
            raise RuntimeError("B 接口任务已完成，但响应缺少有效 result")

        callback(*ASRStatus.COMPLETED.callback_tuple())
        return result_payload

    def _make_segments(self, resp_data: dict) -> List[ASRDataSeg]:
        if self.need_word_time_stamp:
            return [
                ASRDataSeg(w["label"].strip(), w["start_time"], w["end_time"])
                for u in resp_data["utterances"]
                for w in u["words"]
            ]
        else:
            return [
                ASRDataSeg(u["transcript"], u["start_time"], u["end_time"])
                for u in resp_data["utterances"]
            ]


if __name__ == "__main__":
    # Example usage
    audio_file = r"test.mp3"
    asr = BcutASR(audio_file)
    asr_data = asr.run()
    print(asr_data)
