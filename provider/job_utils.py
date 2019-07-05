import inspect

from virttest import qemu_monitor
from virttest import utils_misc
from provider.struct import blockdev

prefix = "x-"

def get_monitor_function(vm):
    """
    Get support function by function name
    """
    caller_name = inspect.stack()[1][3]
    cmd = get_monitor_cmd(caller_name.replace("_", "-"))
    func_name = cmd.replace("-", "_")
    return getattr(vm.monitor, func_name)

def get_monitor_cmd(vm, cmd):
    try:
        vm.monitor.verify_supported_cmd(cmd)
    except qemu_monitor.MonitorNotSupportedCmdError as e:
        cmd = prefix + cmd
        vm.monitor.verify_supported_cmd(cmd)
    return cmd

def make_transaction_action(action_type, arguments):
    """
    Make transaction action dict by arguments
    """
    if not action_type.startswith(prefix):
        for k in arguments.keys():
            if arguments.get(k) is not None:
                arguments.pop(k)
                continue
            if k.startswith(prefix):
                arguments[k.lstrip(prefix)] = arguments.pop(k)
    return {"type": action_type, "data": arguments}

def copy_from_keys(src_dict, keys):
    return {k:v for k,v in src_dict.items() if v is None or k in keys}

def blockdev_create(vm, driver, **kwargs):
    random_id = utils_misc.random_id()
    options = blockdev.BlockDevCreateOptions.get(driver) 
    create_options = copy_from_keys(kwargs, options)
    create_options.update({"driver": driver})
    vm.monitor.blockdev_create(job_id, **create_options)
    return job_id

def blockdev_add(vm,driver,  **kwargs):
    random_id = utils_misc.random_id()
    options = blockdev.BlockDevOptions(driver)
    add_options = copy_from_keys(kwargs, options)
    add_options.update({"driver": driver})
    if "node-name" not in kwargs:
        add_options.update({"node-name": random_id})
    vm.monitor.blockdev_add(**add_options)
    return add_options.get("node-name")

def incremental_backup(vm, device, node, bitmap):
    vm.monitor.block_dirty_bitmap_disbale(deivce, bitmap)
    options = {"device": device, "target": target, "sync": "incremental", "bitmap": bitmap}
    vm.monitor.blockdev_backup(**options)

def block_dirty_bitmap_disable(vm, device, bitmap):
    func = get_monitor_function(vm) 
    func(device, bitmap)
    query_jobs() 


def query_jobs(vm, device):
    func = get_monitor_function(vm)
    return func(device)

def query_job(vm, device, job_id):
    jobs = query_jobs(vm, device)
    try:
        return [j for j in jobs if j["id"] == job_id][0] 
    except IndexError:
        logging.warning("Block job '%s' not exists in device '%s'" % (job_id, device))
    return None 
