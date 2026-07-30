import os
import sys

# Make `config`, `memory`, `retriever`, ... importable when pytest runs from
# the repo instead of the container (where PYTHONPATH=/app already does this).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
