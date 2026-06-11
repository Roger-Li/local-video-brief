from __future__ import annotations

import threading

# Serializes Apple-GPU work (mlx-whisper ASR and in-process mlx-lm generation)
# across the worker pool. RLock because MlxQwenSummaryGenerator._call_llm
# acquires it and then calls _ensure_model_loaded, which acquires it again
# in the same thread.
GPU_LOCK = threading.RLock()
