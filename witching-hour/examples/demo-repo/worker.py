import queue

TASKS = queue.Queue()
STOP = False
MAX_ATTEMPTS = 3

def loop():
    while not STOP:
        task = TASKS.get()
        result = run(task)
        if result == 'retry' and task.attempts < MAX_ATTEMPTS:
            task.attempts += 1
            TASKS.put(task)

def run(task):
    return task()

