import logging
import inspect
from avocado import fail_on
from virttest import utils_misc


@fail_on
def job_dismiss(vm, job_id):
    job = get_job_by_id(vm, job_id)
    msg = "Job '%s' is '%s', only concluded job can dismiss!" % (job_id,job["status"])
    assert job["status"] == "concluded", msg
    func = utils_misc.get_monitor_function(vm)
    return func(job_id)

def get_job_by_id(vm, job_id):
    jobs = query_jobs(vm)
    try:
        return [j for j in jobs if j["id"] == job_id][0]
    except IndexError:
        logging.warning(
            "Block job '%s' not exists" % job_id)
    return None

def query_jobs(vm):
    func = utils_misc.get_monitor_function(vm)
    return func()

