"""
state.py
Shared application state passed between screens.
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AppState:
    # --- file ---
    input_path:    Optional[Path] = None
    output_dir:    Optional[Path] = None

    # --- folder mode ---
    is_folder:          bool = False
    folder_file_count:  int  = 0
    folder_dir_count:   int  = 0
    folder_total_size_mb: float = 0.0
    engine_breakdown:   dict = field(default_factory=dict)

    # --- profile (filled after drop) ---
    entropy:           float = 0.0
    repetitiveness:    float = 0.0
    compression_hint:  float = 0.0
    file_size_mb:      float = 0.0

    # --- constraint ---
    constraint: str = "balanced"
    degree:     str = "balanced"

    # --- recommendation (from selector) ---
    engine:      str   = ""
    level:       int   = 0
    reason:      str   = ""
    alternatives: list = field(default_factory=list)

    # --- prediction (from predictor) ---
    predicted_ratio:          float = 0.0
    predicted_compress_speed: float = 0.0
    predicted_decompress_speed: float = 0.0
    predicted_memory_mb:      float = 0.0
    predicted_compress_time:  float = 0.0
    predicted_decompress_time: float = 0.0
    ratio_low:    float = 0.0
    ratio_high:   float = 0.0
    confidence:   str   = ""
    estimated_output_mb: float = 0.0

    # --- result (filled after compression) ---
    actual_ratio:         float = 0.0
    actual_compress_speed: float = 0.0
    actual_time:          float = 0.0
    actual_output_mb:     float = 0.0
    output_path:          Optional[Path] = None

    # --- settings ---
    db_path: Optional[Path] = Path("data/benchmark.db")

    def reset_file(self):
        """Clear file-specific state when a new file is dropped."""
        self.input_path             = None
        self.is_folder               = False
        self.folder_file_count       = 0
        self.folder_dir_count        = 0
        self.folder_total_size_mb    = 0.0
        self.engine_breakdown        = {}
        self.entropy                = 0.0
        self.repetitiveness         = 0.0
        self.compression_hint       = 0.0
        self.file_size_mb           = 0.0
        self.engine                 = ""
        self.level                  = 0
        self.reason                 = ""
        self.alternatives           = []
        self.predicted_ratio        = 0.0
        self.predicted_compress_speed = 0.0
        self.predicted_decompress_speed = 0.0
        self.predicted_memory_mb    = 0.0
        self.predicted_compress_time = 0.0
        self.predicted_decompress_time = 0.0
        self.ratio_low              = 0.0
        self.ratio_high             = 0.0
        self.confidence             = ""
        self.estimated_output_mb    = 0.0
        self.actual_ratio           = 0.0
        self.actual_compress_speed  = 0.0
        self.actual_time            = 0.0
        self.actual_output_mb       = 0.0
        self.output_path            = None
