import os

# offline tests: no model loading (quote windows ranked by word overlap only)
os.environ.setdefault("MICHAEL_SEMANTIC_WINDOWS", "0")
