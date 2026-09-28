import os
import sys
import tempfile

# Keep every test away from the real ~/.cache/herdr-codexbar; the package reads the state directory on import.
if "herdr_codexbar" in sys.modules:
    raise RuntimeError("herdr_codexbar was imported before the tests could isolate its state; run `python -m unittest discover -s tests -t .`")
os.environ["HERDR_CODEXBAR_STATE"] = tempfile.mkdtemp(prefix="herdr-codexbar-test-")
