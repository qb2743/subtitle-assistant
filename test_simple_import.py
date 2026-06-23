"""测试修复：检查类定义和基本导入"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

print("Test 1: Import voice loader")
try:
    from videocaptioner.core.voices.loader import load_edge_voices, get_all_languages, get_voices_by_language
    voices = load_edge_voices()
    print(f"OK - {len(voices)} languages loaded")
except Exception as e:
    print(f"FAIL - {e}")
    sys.exit(1)

print("\nTest 2: Import UI classes")
try:
    from videocaptioner.ui.view.dubbing_interface import DubbingInterface, ElevenLabsAPITestThread, VoicePreviewThread
    print("OK - All classes imported")
except Exception as e:
    print(f"FAIL - {e}")
    sys.exit(1)

print("\nTest 3: Check VoicePreviewThread is independent")
try:
    import inspect
    # VoicePreviewThread should be a top-level class, not nested
    if VoicePreviewThread.__module__ == 'videocaptioner.ui.view.dubbing_interface':
        print("OK - VoicePreviewThread is properly defined")
    else:
        print("FAIL - VoicePreviewThread module issue")
        sys.exit(1)
except Exception as e:
    print(f"FAIL - {e}")
    sys.exit(1)

print("\nAll tests passed!")
