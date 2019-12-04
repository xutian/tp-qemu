import os
import math
import random
import logging

from avocado.utils import process

from virttest import data_dir
from virttest import env_process
from virttest import qemu_storage
from virttest import utils_libguestfs

from provider import backup_utils
from provider.virt_storage import storage_volume
from provider.virt_storage.storage_admin import sp_admin


class BlockdevBackupSimpleTest(object):

    def __init__(self, test, params, env, source, target):
        self.env = env
        self.test = test
        self.params = params
        self.backup_options = dict(
            params.copy_from_keys(
                params.objects("backup_options")))
        self.source_disk = self.source_disk_define_by_params(params, source)
        self.target_disk = self.target_disk_define_by_param(params, target)
        self.main_vm = self.main_vm_define_by_params(test, env, params, source)

    def generate_random_cluster_size(blacklist):
        """
        generate valid value for cluster size
        :param blacklist: black list of cluster_size value
        :return: int type valid cluster size
        """
        if blacklist is None:
            blacklist = list()
        cluster_size = list(
            filter(
                lambda x: math.log2(x).is_integer(),
                range(
                    512,
                    2097152,
                    1)))
        pool = set(cluster_size) - set(blacklist)
        return random.choice(list(pool))

    def source_disk_define_by_params(self, params, image_name):
        base_dir = data_dir.get_data_dir()
        images_dir = os.path.join(base_dir, "images")
        image_params = params.object_params(image_name)
        if self.params.get("random_cluster_size") == "yes":
            blacklist = list(
                map(int, self.params.objects("cluster_size_blacklist")))
            cluster_size = self.generate_random_cluster_size(blacklist)
            image_params["image_cluster_size"] = cluster_size
            logging.info(
                "set source image cluster size to '%s'" %
                cluster_size)
        return qemu_storage.QemuImg(image_params, images_dir, image_name)

    def target_disk_define_by_param(self, params, image_name):
        if self.params.get("random_cluster_size") == "yes":
            blacklist = list(
                map(int, self.params.objects("cluster_size_blacklist")))
            cluster_size = self.generate_random_cluster_size(blacklist)
            params["image_cluster_size"] = cluster_size
            logging.info(
                "set target image cluster size to '%s'" %
                cluster_size)
        return sp_admin.volume_define_by_params(image_name, params)

    def main_vm_define_by_params(self, test, env, params, source):
        for vm in self.env.get_all_vms():
            if vm.is_alive():
                vm.destroy()
        vm_name = params["main_vm"]
        vm_params = params.object_params(vm_name)
        images = vm_params.get("images")
        if source not in images:
            images += " %s" % source
        vm_params["images"] = images
        vm_params["start_vm"] = "yes"
        env_process.preprocess_vm(test, vm_params, env, vm_name)
        return env.get_vm(vm_name)

    def format_disk(self, disk, filesystem, partition="mbr"):
        image_path, image_format = None, None
        if isinstance(disk, qemu_storage.QemuImg):
            image_path = disk.image_filename
            image_format = disk.image_format
        elif isinstance(disk, storage_volume.StorageVolume):
            image_path = disk.key
            image_format = disk.format.TYPE
        else:
            raise ValueError("Unsupport disk type: %s" % type(disk))

        selinux_mode = process.getoutput("getenforce", shell=True)
        try:
            process.getoutput("setenforce 0")
            utils_libguestfs.virt_format(
                image_path,
                filesystem=filesystem,
                image_format=image_format,
                partition=partition)
        finally:
            process.system("setenforce %s" % selinux_mode)

    def prepare_source_disk(self):
        params = self.params.object_params(self.source_disk.tag)
        self.source_disk.create(params)
        filesystem = params.get("filesystem", "ext4")
        partition = params.get("partition", "mbr")
        self.format_disk(self.source_disk, filesystem, partition)

    def prepare_test(self):
        self.prepare_source_disk()
        self.main_vm.create()
        self.main_vm.verify_alive()
        self.prepare_target_image()
        self.target_disk.hotplug_qmp(self.main_vm)

    def do_backup(self):
        """
        Backup source image to target image

        :param params: test params
        :param source_img: source image name or tag
        :param target_img: target image name or tag
        """
        logging.info(
            "backup %s to %s" %
            (self.source_disk.tag,
             self.target_disk.name))
        source_name = "drive_%s" % self.source_disk.tag
        target_name = "drive_%s" % self.target_disk.name
        backup_utils.full_backup(
            self.main_vm,
            source_name,
            target_name,
            **self.backup_options)

    def post_test(self):
        self.main_vm.destroy()
        if self.backup_options.get("sync", "full"):
            self.source_disk.compare_images(
                self.source_disk.image_filename,
                self.target_disk.path,
                force_share=True)
        sp_admin.remove_volume(self.target_disk)

    def run_test(self):
        self.prepare_test()
        try:
            self.do_backup()
        finally:
            self.post_test()
