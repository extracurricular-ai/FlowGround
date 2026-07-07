import sys
from pathlib import Path

# Make `import app.*` work no matter where pytest is invoked from.
SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
