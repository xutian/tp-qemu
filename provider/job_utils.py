import inspect
from avocado import fail_on
from virttest import qemu_monitor
from virttest import utils_misc
from provider.struct import blockdev

prefix = "x-"


def copy_from_keys(src_dict, keys):
    return {k: v for k, v in src_dict.items() if v is None or k in keys}


def get_monitor_function(vm):
    """
    Get support function by function name
    """
    caller_name = inspect.stack()[1][3]
    cmd = get_monitor_cmd(caller_name.replace("_", "-"))
    func_name = cmd.replace("-", "_")
    return getattr(vm.monitor, func_name)


def get_monitor_cmd(vm, cmd):
    """
    Wrapper to get monitor function
    """
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


@fail_on
def create_target_block_device(vm, device, **image_args, **device_args):
    job_id, filename = blockdev_create(vm, **image_args)
    node_name = blockdev_add(vm, **device_args)
    assert get_block_node_by_name(node_name), "node '%s' not exists" % node_name 

def blockdev_create(vm, driver, **kwargs):
    random_id = utils_misc.random_id()
    options = blockdev.BlockDevCreateOptions.get(driver)
    create_options = copy_from_keys(kwargs, options)
    create_options.update({"driver": driver})
    vm.monitor.blockdev_create(job_id, **create_options)
    return job_id


def blockdev_add(vm, driver, **kwargs):
    """
    Add block backing device
    """
    random_id = utils_misc.random_id()
    options = blockdev.BlockDevOptions(driver)
    add_options = copy_from_keys(kwargs, options)
    add_options.update({"driver": driver})
    if "node-name" not in kwargs:
        add_options.update({"node-name": random_id})
    vm.monitor.blockdev_add(**add_options)
    return add_options.get("node-name")

@fail_on
def incremental_backup(vm, node, target, bitmap=None):
    """
    Do incremental backup with bitmap
    """
    info = query_block_dirty_bitmap_by_name(vm, node, bitmap)
    if not info["disabled"]:
        block_dirty_bitmap_disbale(vm, node, bitmap)
    options = {
        "device": node,
        "target": target,
        "sync": "incremental"}
    if bitmap:
        options["bitmap"] = bitmap
    return vm.monitor.blockdev_backup(**options)

@fail_on
def full_backup(vm, node, target):
    #FixMe:
    #    Not compare image after full backup image here,
    # because we are not pause write requests to node.
    node = query_block_dirty_bitmap_by_name(target)
    if not node:
        logging.error("target node '%s' not exists" % target)
    else:
        options = {
            "device": node,
            "target": target,
            "sync": "full"}
    return vm.monitor.blockdev_backup(**options)
     


@fail_on
def block_dirty_bitmap_disable(vm, node, name):
    func = get_monitor_function(vm)
    func(node, name)
    bitmap = query_block_dirty_bitmap_by_name(vm, node, name)
    assert bitmap.get(
        "disabled"), "block dirty bitmap '%s' is not disabled" % name


def query_block_dirty_bitmap(vm, node):
    func = get_monitor_function(vm)
    return func(node)


def query_block_dirty_bitmap_by_name(vm, node, name):
    for item in query_block_dirty_bitmap(vm, node):
        if item.get("name") == name:
            return item
    return None


def query_jobs(vm, device):
    func = get_monitor_function(vm)
    return func(device)


def query_job(vm, device, job_id):
    jobs = query_jobs(vm, device)
    try:
        return [j for j in jobs if j["id"] == job_id][0]
    except IndexError:
        logging.warning(
            "Block job '%s' not exists in device '%s'" %
            (job_id, device))
    return None

def get_block_node_by_name(vm, node):
    """
    Get block node info by node name
    """
    info = query_named_block_nodes(vm)
    return [ i for i in info if i["node-name"] == node][0] 

def query_named_block_nodes(vm):
    """
    Get all block nodes info
    """
    func = get_monitor_function(vm)
    return func()
