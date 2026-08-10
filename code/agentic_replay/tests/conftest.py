import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))                   # code/agentic_replay
sys.path.insert(0, str(HERE.parents[2] / "tinker_sweep"))  # render, families, train_sft
