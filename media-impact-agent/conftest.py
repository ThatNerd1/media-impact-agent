import sys
from pathlib import Path

# Damit Pytest src/db.py und src/schemas.py ohne src.-Prefix importieren kann.
sys.path.insert(0, str(Path(__file__).parent / "src"))
