import logging
import inspect
from avocado import fail_on
from virttest import utils_misc
from provider import block_dirty_bitmap as block_bitmap



def make_transaction_action(cmd, data):
    """
    Make transaction action dict by arguments
    """
    prefix = "x-"
    if not cmd.startswith(prefix):
        for k in data.keys():
            if data.get(k) is None:
                data.pop(k)
                continue
            if k.startswith(prefix):
                data[k.lstrip(prefix)] = data.pop(k)
    return {"type": cmd, "data": data}


def blockdev_create(vm, options, job_id=None):
    if not job_id:
        job_id = utils_misc.generate_random_id()
    func = utils_misc.get_monitor_function(vm)
    func(job_id, options)
    return job_id


def blockdev_backup(vm, options, job_id=None):
    if not job_id:
        job_id = utils_misc.generate_random_id()
    func = utils_misc.get_monitor_function(vm)
    return func(job_id, options) 


def blockdev_add(vm, options):
    """
    Add block backing device
    """
    if "node-name" not in options:
        options["node-name"] = utils_misc.generate_random_id()
    func = utils_misc.get_monitor_function(vm) 
    func(options)
    return options["node-name"]


def get_block_node_by_name(vm, node):
    """
    Get block node info by node name
    """
    info = query_named_block_nodes(vm)
    return [i for i in info if i["node-name"] == node][0]


def query_named_block_nodes(vm):
    """
    Get all block nodes info
    """
    func = utils_misc.get_monitor_function(vm)
    return func()

@fail_on
def incremental_backup(vm, node, target, bitmap=None):
    """
    Do incremental backup with bitmap
    """
    get_block_node_by_name(vm, target) 
    info = block_bitmap.query_block_dirty_bitmap_by_name(vm, node, bitmap)
    if not info["disabled"]:
        block_bitmap.block_dirty_bitmap_disbale(vm, node, bitmap)
    options = {
        "job-id": utils_misc.generate_random_id(),
        "device": node,
        "target": target,
        "sync": "incremental"}
    if bitmap:
        options["bitmap"] = bitmap
    return blockdev_backup(vm, options)


@fail_on
def full_backup(vm, node, target):
    # FixMe:
    #    Not compare image after full backup image here,
    # because we are not pause write requests to node.
    get_block_node_by_name(vm, target) 
    options = {
            "job-id": utils_misc.generate_random_id(),
            "device": node,
            "target": target,
            "sync": "full"}
    return blockdev_backup(vm, options)
