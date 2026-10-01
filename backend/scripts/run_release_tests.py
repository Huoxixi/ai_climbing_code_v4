"""Production regression suite, including every replay extension.

The development-only simulation API suite requires ENABLE_SIMULATION=true and
is run separately. Production closure is verified by test_release_hardening.
Use an isolated copy of the repository fixtures for local release verification.
"""
import os
from pathlib import Path
import sys
import unittest

backend = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(backend))
os.environ.setdefault("LOCAL_ONLY", "true")
os.environ.setdefault("DISABLE_SUPABASE", "true")
os.environ.setdefault("ENABLE_SIMULATION", "false")
modules = [path.stem for path in sorted(backend.glob("test_*.py"))
           if path.name != "test_simulation.py"]
suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(not result.wasSuccessful())
