"""Part 8: same real-data FlyBrain check as Part 4, now through the worker process.
(Guarded: on Windows the worker process re-imports the launching script.)"""
import runpy

if __name__ == "__main__":
    runpy.run_path("test_runs/_part8_flybrain_body.py", run_name="flybrain_body")
