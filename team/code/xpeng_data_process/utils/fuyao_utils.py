import subprocess
import threading
import time
from datetime import datetime


def print_current_time():
    while not stop_thread:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"Current Time: {current_time}", flush=True)
        time.sleep(10)


def run_cmd_and_log(cmd):
    global stop_thread
    stop_thread = False

    # Start the thread to print current time
    time_thread = threading.Thread(target=print_current_time)
    time_thread.start()  # prevent fuyao from stoping the job if no print out

    try:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True
        )
        stdout, stderr = process.communicate()
        out = stdout.decode()
        out_err = stderr.decode()
        print(f"STDOUT ======= \n{out}", flush=True)
        print(f"STDERR ======= \n{out_err}", flush=True)
    finally:
        stop_thread = True
        time_thread.join()
        print()  # Move to the next line after stopping the time print