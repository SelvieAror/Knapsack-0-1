import random
import multiprocessing as mp
import sys
import struct
import time
import ctypes
from ctypes import wintypes
import statistics

MEMORY_LIMIT_MB = 2000

LEVELS = {
    "easy": [10, 15, 20, 25, 30],
    "medium": [35, 40, 50, 100, 200, 500],
    "hard": [100, 200, 500, 1000],
}
 
SEEDS = [1, 2, 3, 4, 5]
 
 
def generate(n, level, seed):
    if n > 1000:
        raise ValueError("n must be <= 1000")
    rng = random.Random(seed)

    match level:
        case "easy":
            weight = [rng.randint(1, 50) for _ in range(n)]
            value = [rng.randint(1, 100) for _ in range(n)]
            p = 0.5

        case "medium":
            weight = [rng.randint(1, 1000) for _ in range(n)]
            value = [w + rng.randint(0, 100) for w in weight]
            p = 0.3

        case "hard":
            weight = [rng.randint(10**4, 10**6) for _ in range(n)]
            value = [w + 1000 for w in weight]
            p = 0.5

        case _:
            raise ValueError("Invalid level")

    capacity = int(p * sum(weight))

    return weight, value, capacity


def brute(weight, value, capacity):
    n = len(weight)
    max_value = 0
    best_combination = []
    total_weight = 0
    total_value = 0
    selected = [False] * n
    previous_gray = 0

    for i in range(1 << n):
        gray = i ^ (i >> 1)

        if i > 0:
            changed_bit = gray ^ previous_gray
            j = changed_bit.bit_length() - 1

            if gray & changed_bit:
                selected[j] = True
                total_weight += weight[j]
                total_value += value[j]
            else:
                selected[j] = False
                total_weight -= weight[j]
                total_value -= value[j]

        previous_gray = gray

        if total_weight <= capacity and total_value > max_value:
            max_value = total_value
            best_combination = [
                j for j in range(n) if selected[j]
            ]

    return max_value, best_combination


def dp_memory_check(n, capacity):
    rows = n + 1
    columns = capacity + 1
    cells = rows * columns

    bytes_per_cell = sys.getsizeof(0) + struct.calcsize("P")

    estimated_bytes = (
        cells * bytes_per_cell
        + rows * sys.getsizeof([])
        + sys.getsizeof([])
    )

    limit_bytes = MEMORY_LIMIT_MB * 1024 * 1024

    return estimated_bytes <= limit_bytes


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def peak_memory_mb():
    try:
        kernel32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")

        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)

        if not psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            return None

        return counters.PeakWorkingSetSize / (1024 * 1024)

    except Exception:
        return None


def worker(connection, function, args):
    try:
        result = function(*args)

        if isinstance(result, tuple) and result[0] == "MEMOUT":
            connection.send("MEMOUT")
        else:
            connection.send(result)

    except MemoryError:
        connection.send("MEMOUT")

    except Exception:
        connection.send("ERROR")

    finally:
        connection.close()


def run_with_timeout(function, args, timeout_seconds=1800):
    parent, child = mp.Pipe(duplex=False)

    process = mp.Process(
        target=worker,
        args=(child, function, args)
    )

    process.start()
    child.close()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join()
        parent.close()
        return "TIMEOUT"

    if parent.poll():
        try:
            answer = parent.recv()
        except EOFError:
            answer = "ERROR"
    else:
        answer = "ERROR"

    parent.close()
    return answer

def dynamic_programming(weight, value, capacity):
    n = len(weight)

    if not dp_memory_check(n, capacity):
        return "MEMOUT", None

    try:
        dp = [
            [0 for _ in range(capacity + 1)]
            for _ in range(n + 1)
        ]
    except MemoryError:
        return "MEMOUT", None

    for i in range(1, n + 1):
        for w in range(capacity + 1):
            if weight[i - 1] <= w:
                dp[i][w] = max(
                    dp[i - 1][w],
                    value[i - 1] + dp[i - 1][w - weight[i - 1]]
                )
            else:
                dp[i][w] = dp[i - 1][w]

    max_value = dp[n][capacity]
    combination = []
    w = capacity

    for i in range(n, 0, -1):
        if dp[i][w] != dp[i - 1][w]:
            combination.append(i - 1)
            w -= weight[i - 1]

    combination.reverse()

    return max_value, combination

def measure_time(function, args, timeout=1800):

    times = []

    for i in range(5):

        start = time.perf_counter()

        answer = run_with_timeout(function, args, timeout)

        elapsed = time.perf_counter() - start

        if answer in ("TIMEOUT", "ERROR", "MEMOUT"):
            return answer, None

        times.append(elapsed)

        # If the first run takes 1 second or more,
        # we don't need to repeat it.
        if i == 0 and elapsed >= 1:
            break

    median_time = statistics.median(times)

    return answer, median_time

if __name__ == "__main__":

    TIME_LIMIT = 1800

    for level, sizes in LEVELS.items():
        print("LEVEL:", level.upper())

        brute_stopped = False
        dp_stopped = False

        for n in sizes:

            print("\nNumber of items:", n)

            for seed in SEEDS:

                print("\nSeed:", seed)

                
                start = time.perf_counter()
                weight, value, capacity = generate(n, level, seed)
                generation_time = time.perf_counter() - start

                print("Capacity:", capacity)
                print("Generation time:", generation_time)

               
                if not brute_stopped:

                    print("\nRunning brute force...")

                    start = time.perf_counter()

                    brute_answer = run_with_timeout(
                        brute,
                        (weight, value, capacity),
                        TIME_LIMIT
                    )

                    elapsed = time.perf_counter() - start

                    if brute_answer == "TIMEOUT":
                        print("Brute force: TIMEOUT")
                        brute_stopped = True

                    elif brute_answer == "ERROR":
                        print("Brute force: ERROR")

                    else:
                        print("Brute force value:", brute_answer[0])
                        print("Solution size:", len(brute_answer[1]))
                        print("Time:", elapsed)

                else:
                    print("Brute force: skipped (previous timeout)")

               
                if not dp_stopped:

                    print("\nRunning dynamic programming...")

                    start = time.perf_counter()

                    dp_answer = run_with_timeout(
                        dynamic_programming,
                        (weight, value, capacity),
                        TIME_LIMIT
                    )

                    elapsed = time.perf_counter() - start

                    if dp_answer == "TIMEOUT":
                        print("Dynamic programming: TIMEOUT")
                        dp_stopped = True

                    elif dp_answer == "MEMOUT":
                        print("Dynamic programming: MEMOUT")

                    elif dp_answer == "ERROR":
                        print("Dynamic programming: ERROR")

                    else:
                        print("DP value:", dp_answer[0])
                        print("Solution size:", len(dp_answer[1]))
                        print("Time:", elapsed)

                else:
                    print("Dynamic programming: skipped (previous timeout)")

               
                if (not brute_stopped or brute_answer != "TIMEOUT") and (
                    not dp_stopped or dp_answer != "TIMEOUT"
                ):
                    if isinstance(brute_answer, tuple) and isinstance(dp_answer, tuple):
                        if brute_answer[0] == dp_answer[0]:
                            print("Both algorithms returned the same value!")
                        else:
                            print("ERROR: Different answers!")
