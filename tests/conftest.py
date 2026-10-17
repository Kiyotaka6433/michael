import os
import tempfile

# offline tests: no model loading (quote windows ranked by word overlap only), and a throwaway database
os.environ.setdefault("MICHAEL_SEMANTIC_WINDOWS", "0")
os.environ.setdefault("MICHAEL_DATA_DIR", tempfile.mkdtemp(prefix="michael-test-"))
