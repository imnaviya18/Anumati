from config.celery import app
from apps.deadlines.services import scan_durable_due_work_register


@app.task(name="deadlines.scan_due")
def scan_due_task():
    return scan_durable_due_work_register()
