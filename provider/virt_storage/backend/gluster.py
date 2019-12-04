from provider.virt_storage import storage_volume
from provider.virt_storage.backend import nfs
from provider.virt_storage.utils import storage_util


class GlusterPool(nfs.NfsPool):
    TYPE = "gluster"

    def find_sources(self):
        urls = list()
        for path in self.helper.list_files():
            urls.append(self.helper.path_to_url(path))
        return urls

    def create_volume_from_remote(self, url):
        volume = storage_volume.StorageVolume(self)
        volume.url = volume.path = url
        volume.capacity = self.helper.get_size(url)
        volume.is_allocated = True
        return volume

    def remove_volume(self, volume):
        self.helper.remove_image(volume.url)
        self._volumes.discard(volume)

    def create_volume(self, volume):
        storage_util.create_volume(volume)
        volume.is_allocated = True
        return volume
