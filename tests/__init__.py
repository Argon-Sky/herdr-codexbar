import os
import tempfile

# Keep every test away from the real ~/.cache/herdr-codexbar.
os.environ["HERDR_CODEXBAR_STATE"] = tempfile.mkdtemp(prefix="herdr-codexbar-test-")
