# save_result.py

import os
import json
from datetime import datetime


def save_test_result(name: str, data: dict, base_dir: str = "tests/results",
                     run_id: str | None = None) -> str:
    """
    Save test results into a timestamped JSON file.

    Parameters
    ----------
    name : str
        Short test name, e.g. "single_led", "dual_led", "cpu_load".
    data : dict
        A dictionary containing measured metrics. Must be JSON-serializable.
    base_dir : str
        Directory where result files are stored. Default: "tests/results".
    run_id : str | None
        If provided, this string will be used as the timestamp part of
        the filename. This allows multiple scripts to share the same ID
        for a single combined run. If None, the current datetime is used.

    Returns
    -------
    filepath : str
        The full path of the JSON file that was created.
    """
    os.makedirs(base_dir, exist_ok=True)

    # If no run_id is provided, generate one from current time
    if run_id is None:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    filename = f"{name}_{run_id}.json"
    filepath = os.path.join(base_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

    print(f"\n[Saved] Test results saved to: {filepath}")
    return filepath
