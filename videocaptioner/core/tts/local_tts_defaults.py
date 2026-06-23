"""本地 Gradio TTS（Dots-TTS / VoxCPM）默认项目地址与环境包 URL。

环境包 URL 来源：
- VoxCPM：pyvideotrans F5-TTS 教程页列出的 Windows 整合包（与 F5/Index 等同页说明）
  https://pyvideotrans.com/f5tts
- Dots-TTS：无官方一键 zip，需从项目仓库自行部署 Gradio 服务。
"""

DOTS_TTS_PROJECT_URL = "https://github.com/rednote-hilab/dots.tts"
VOXCPM_PROJECT_URL = "https://github.com/OpenBMB/VoxCPM"
PYVIDEOTRANS_F5TTS_TUTORIAL_URL = "https://pyvideotrans.com/f5tts"

# pyvideotrans F5-TTS 教程页提供的 Windows 整合包（F5-TTS，与 VoxCPM 同页说明部署方式）
PYVIDEOTRANS_F5_TTS_BUNDLE_URL = (
    "https://huggingface.co/mortimerme/repocollect/resolve/main/f5-tts0528.7z"
)

# VoxCPM：pyvideotrans 教程未单独给出 zip，默认同页 Windows 整合包（用户可按需改填专用地址）
DEFAULT_VOXCPM_PACKAGE_URL = PYVIDEOTRANS_F5_TTS_BUNDLE_URL
DEFAULT_DOTS_PACKAGE_URL = ""