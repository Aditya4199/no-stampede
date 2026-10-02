import subprocess
import time
import os

try:
    process = subprocess.Popen(
        [os.path.expanduser(r"~\.fly\bin\flyctl.exe"), "logs", "-a", "no-stampede"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    time.sleep(5)
    process.terminate()
    stdout, stderr = process.communicate()
    print("STDOUT:\n", stdout)
    print("STDERR:\n", stderr)
except Exception as e:
    print("Error:", e)
