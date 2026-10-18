import os
import tempfile

# Isolate the database, keys and evidence from the real runtime folder, and keep tests
# fast: no model loading.
os.environ.setdefault("COUNTERSIGN_RUNTIME", tempfile.mkdtemp(prefix="cs-test-"))
os.environ.setdefault("COUNTERSIGN_S1", "dummy")
os.environ.setdefault("COUNTERSIGN_S2", "0")
os.environ.setdefault("COUNTERSIGN_STAFF_PIN", "4321")
os.environ.setdefault("COUNTERSIGN_EVAL", "1")
os.environ.setdefault("COUNTERSIGN_ASR", "off")
