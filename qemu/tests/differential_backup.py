import logging
import time

from virttest import error_context
from virttest import storage
from virttest import utils_misc
from virttest import qemu_monitor
from qemu.tests import live_backup_base


class DifferentialBackupTest(live_backup_base.LiveBackup):

    def __init__(self, test, params, env, tag):
        super(DifferentialBackupTest, self).__init__(test, params, env, tag)
        self.bitmaps = []
        self.device = "drive_%s" % tag

    def generate_backup_params(self):
        """
        Generate params from source image params for target image
        :return: dict contain params for create target image
        """
        image_params = self.params.object_params(self.tag)
        image_params["image_format"] = "qcow2"
        return image_params

    def init_data_disk(self):
        """Initialize the data disk"""
        session = self.get_session()
        for param in ["format_disk_cmd", "mount_disk_cmd"]:
            if self.params.get(param):
                cmd = self.params[param]
                session.cmd(cmd)
                time.sleep(0.5)
        session.close()

    def get_image_size(self):
        image_params = self.generate_backup_params()
        source_image = storage.QemuImg(image_params, self.data_dir, self.tag)
        image_filename = source_image.image_filename
        image_size = super(DifferentialBackupTest,
                           self).get_image_size(image_filename)
        return (image_size // 512 + 1) * 512

    def create_target_block_device(self, backing_node=None, backing_file=None):
        """Create target backup device by qemu"""
        jobs = []
        driver = "file"
        driver_fmt = "qcow2"
        node_name = utils_misc.generate_random_id()
        driver_node_name = "driver_%s" % node_name
        image_params = self.generate_backup_params()
        image_params["image_name"] = node_name
        img_obj = storage.QemuImg(image_params, self.data_dir, self.tag)
        target_image_file = img_obj.image_filename
        target_image_size = self.get_image_size()
        options = {"filename": target_image_file, "driver": driver, "size": 0}
        try:
            jobs += [self.vm.monitor.blockdev_create(**options)]
            self.trash_files.append(target_image_file)
            time.sleep(3)
            options = {"driver": driver, "node-name": driver_node_name,
                       "filename": target_image_file}
            self.vm.monitor.blockdev_add(options)
            options = {"file": driver_node_name,
                       "driver": driver_fmt, "size": target_image_size}
            if backing_file:
                options["backing-file"] = backing_file
                options["backing-fmt"] = driver_fmt
            jobs += [self.vm.monitor.blockdev_create(**options)]
            time.sleep(3)
            options = {"driver": driver_fmt,
                       "file": driver_node_name, "node-name": node_name}
            if backing_file:
                options["backing"] = backing_node
            self.vm.monitor.blockdev_add(options)
        finally:
            jobs_info = str(self.vm.monitor.cmd("query-jobs"))
            jobs = [_ for _ in jobs if _ in jobs_info]
            map(self.vm.monitor.job_dismiss, jobs)
        return node_name, target_image_file

    @staticmethod
    def _make_transaction_action(action_type, arguments):
        if not action_type.startswith(qemu_monitor.IMMATURE_CMD_PREFIX):
            for k in arguments.keys():
                if not arguments.get(k):
                    arguments.pop(k)
                    continue
                if k.startswith(qemu_monitor.IMMATURE_CMD_PREFIX):
                    arguments[k.lstrip(
                        qemu_monitor.IMMATURE_CMD_PREFIX)] = arguments.pop(k)
        return {"type": action_type, "data": arguments}

    def _make_bitmap_transaction_action(self, action="add", index=1, **extra_options):
        bitmap = "bitmap_%d" % index
        action_type = "block-dirty-bitmap-%s" % action
        action_data = {"node": self.device, "name": bitmap}
        action_type = self.vm.monitor.shift_immature_cmd(action_type)
        action_data.update(extra_options)
        logging.debug("%s bitmap %s" % (action.capitalize, bitmap))
        return self._make_transaction_action(action_type, action_data)

    def _bitmap_batch_operate_by_transaction(self, action, bitmap_index_list):
        bitmap_lists = ",".join(
            map(lambda x: "bitmap_%d" % x, bitmap_index_list))
        logging.info("%s %s in a transaction" %
                     (action.capitalize(), bitmap_lists))
        actions = map(lambda x: self._make_bitmap_transaction_action(
            action=action, index=x), bitmap_index_list)
        return self.vm.monitor.transaction(actions)

    def get_sha256_of_bitmap(self, bitmap):
        """Return sha256 vaule of bitmap"""
        kwargs = {"node": self.device, "name": bitmap}
        out = self.vm.monitor.debug_block_dirty_bitmap_sha256(**kwargs)
        return out["sha256"]

    def get_record_counts_of_bitmap(self, bitmap):
        """Return bitmap record count"""
        out = self.vm.monitor.cmd("query-block")
        for item in out:
            if item["device"] == self.device:
                for bitmap in item["dirty-bitmaps"]:
                    if bitmap["name"] == bitmap:
                        return int(bitmap["count"])
        return -1

    def do_full_backup(self):
        """Do full backup"""
        node_name, file_name = self.create_target_block_device()
        action_data = {
            "device": self.device,
            "target": node_name,
            "sync": "full"}
        actions = [self._make_transaction_action(
            "blockdev-backup", action_data)]
        actions += self._bitmap_batch_operate_by_transaction("add", [1, 2])
        self.vm.monitor.transaction(actions)
        return node_name, file_name

    def _track_file_with_bitmap(self, filename, action_items):
        """
        Track file with bitmap

        :param filename: full path of file will create
        :param action_items: list of bitmap action.
                             eg, [{"action": add, "index": 1}
        """
        self.create_file(filename)
        actions = []
        for item in action_items:
            operator = item["action"]
            bitmap = item["index"]
            actions += [self._make_transaction_action(operator, bitmap)]
        self.vm.monitor.transaction(actions)

    def track_file1_with_bitmap2(self):
        """track file1 with bitmap2"""
        action_items = [{"action": "disabled", "index": 2},
                        {"action": "add", "index": 3}]
        self._track_file_with_bitmap("file1", action_items)

    def track_file2_with_bitmap3(self):
        """track file2 with bitmap3"""
        action_items = [{"action": "disable", "index": 1},
                        {"action": "disable", "index": 3}]
        self._track_file_with_bitmap("file2", action_items)

    def merge_bitmap2_and_bitmap3_to_bitmap4(self):
        """merged bitmap2 and bitmap3 into bitmap4"""
        target_bitmap = "bitmap_4"
        kwargs = {"x-disabled": True}
        cmd = "x-block-dirty-bitmap-merge"
        cmd = self.vm.monitor.shift_immature_cmd(cmd)
        bitmaps = map(lambda x: "bitmap_%d" % x, [2, 3])
        actions = [self._make_bitmap_transaction_action("add", 4, **kwargs)]
        if cmd.startswith(qemu_monitor.IMMATURE_CMD_PREFIX):
            for bitmap in bitmaps:
                data = {"node": self.device,
                        "src_name": bitmap,
                        "dst_name": target_bitmap}
                actions += [self._make_transaction_action(cmd, data)]
        else:
            data = {"node": self.device,
                    "bitmaps": bitmaps,
                    "target": target_bitmap}
            actions += [self._make_transaction_action(cmd, data)]
        self.vm.monitor.transaction(actions)

    def track_file3_with_bitmap5(self):
        """track file3 with bitmap5"""
        self.vm.monitor.block_dirty_bitmap_add(self.device, "bitmap_5")
        self.create_file("file3")

    def merge_bitmap5_to_bitmap4(self):
        """Merge bitmap5 to bitmap4"""
        kwargs = {"node": self.device, "bitmaps": [
            "bitmap_5"], "target": "bitmap_4"}
        self.vm.monitor.block_dirty_bitmap_merge(**kwargs)

    def do_incremental_backup_with_bitmap4(self, base_node, base_image):
        """Do incremental backup with bitmap4"""
        bitmap, sync = "bitmap_4", "incremental"
        node_name, image_file = self.create_target_block_device(
            base_node, base_image)
        options = {"device": self.device, "target": node_name,
                   "sync": sync, "bitmap": bitmap}
        self.vm.monitor.blockdev_backup(**options)
        return node_name, image_file

    def clean(self):
        """Stop bitmaps and clear image files"""
        self._bitmap_batch_operate_by_transaction(
            "clear", range(1, len(self.bitmaps) + 1))
        for x in range(len(self.bitmaps)):
            bitmap = "bitmap_%d" % x
            counts = self.get_record_counts_of_bitmap(bitmap)
            if counts != 0:
                raise self.test.fail(
                    "Count of %s is not '0' after clear bitmap step." % bitmap)
            self.vm.monitor.block_dirty_bitmap_remove(
                self.device, "bitmap_%d" % x)
            if counts != -1:
                raise self.test.fail(
                    "'%s' still exists after remove bitmap step." % bitmap)
        super(DifferentialBackupTest, self).clean()


@error_context.context_aware
def run(test, params, env):
    """
    Differential Backup Test
    1). boot VM with 2G data disk
    2). create bitmap1, bitmap2 to track changes in data disk
    3). do full backup for data disk
    4). create file1 in data disk and track it with bitmap2
    5). create file2 in data disk and track it with bitmap3
    6). merge bitmap2 and bitmap3 to bitmap4
    7). create file3 in data disk and track it with bitmap5
    8). merge bitmap5 to bitmap4
    9). do incremental backup with bitmap4
    10). reset and remove all bitmaps

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image2")
    backup_test = DifferentialBackupTest(test, params, env, tag)
    try:
        error_context.context("Initialize data disk", logging.info)
        backup_test.init_data_disk()
        error_context.context("Do full backup", logging.info)
        node_name, image_file = backup_test.do_full_backup()
        error_context.context("track file1 in bitmap2", logging.info)
        backup_test.track_file1_with_bitmap2()
        error_context.context("track file2 in bitmap3", logging.info)
        backup_test.track_file2_with_bitmap3()
        error_context.context(
            "Record counts & sha256 of bitmap1", logging.info)
        sha256_bitmap1 = backup_test.get_sha256_of_bitmap("bitmap_1")
        record_counts_bitmap1 = backup_test.get_record_counts_of_bitmap(
            "bitmap_1")
        error_context.context(
            "Merge bitmap2 and bitmap3 to bitmap4", logging.info)
        backup_test.merge_bitmap2_and_bitmap3_to_bitmap4()
        error_context.context("Record sha256 of bitmap4", logging.info)
        sha256_bitmap4 = backup_test.get_sha256_of_bitmap("bitmap_4")
        error_context.context("Record count of bitmap4", logging.info)
        record_counts_bitmap4 = backup_test.get_record_counts_of_bitmap(
            "bitmap_4")
        if sha256_bitmap4 != sha256_bitmap1:
            logging.debug("sha256_bitmap1: %d, sha256_bitmap4: %d" %
                          (sha256_bitmap1, sha256_bitmap4))
            raise test.fail("sha256 of bitmap4 not equal sha256 of bitmap1")
        if record_counts_bitmap4 != record_counts_bitmap1:
            logging.debug("count_bitmap1: %d, count_bitmap4: %d" %
                          (record_counts_bitmap1, record_counts_bitmap4))
            raise test.fail("counts of bitmap4 not equal counts of bitmap4")
        error_context.context("track file3 in bitmap5", logging.info)
        backup_test.track_file3_with_bitmap5()
        error_context.context("Merge bitmap5 in bitmap4", logging.info)
        backup_test.merge_bitmap5_to_bitmap4()
        error_context.context(
            "Do incremental backup with bitmap4", logging.info)
        backup_test.do_incremental_backup_with_bitmap4(node_name, image_file)
    finally:
        backup_test.clean()
