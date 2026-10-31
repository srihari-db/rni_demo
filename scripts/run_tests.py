"""Run the pytest suite on Databricks serverless, including LIVE checks against the loaded Unity Catalog tables.
Writes a JUnit report next to the landing data so results are inspectable after the job run."""
from __future__ import annotations

import os
import sys
from pathlib import Path

def _repo_root():
    try:
        return Path(__file__).resolve().parents[1]
    except NameError:  # serverless spark_python_task does not define __file__
        if "--root" in sys.argv:
            return Path(sys.argv[sys.argv.index("--root") + 1])
        return Path.cwd()


ROOT = _repo_root()
sys.path.insert(0, str(ROOT))


def main(argv=None):
    import argparse
    import shutil
    import tempfile
    sys.dont_write_bytecode = True           # workspace files are read-only for __pycache__
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    import pytest
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", default="rni_demo")
    p.add_argument("--root", default=None)
    a = p.parse_args(argv)
    os.environ["RNI_LIVE"] = "1"
    os.environ["RNI_CATALOG"] = a.catalog
    report = f"/Volumes/{a.catalog}/bronze/landing/test_report.xml"
    work = Path(tempfile.mkdtemp(prefix="rni_tests_"))      # run from a local copy (no writes to /Workspace)
    for d in ("src", "tests", "config", "scripts", "sql", "app", "dashboards"):
        shutil.copytree(ROOT / d, work / d, ignore=shutil.ignore_patterns("__pycache__"))
    sys.path.insert(0, str(work))
    code = pytest.main([str(work / "tests"), "-q", "-p", "no:cacheprovider", f"--junitxml={report}", "-rA",
                        f"--rootdir={work}"])
    if code != 0:
        raise SystemExit(f"pytest failed with exit code {code}")


if __name__ == "__main__":
    main()
