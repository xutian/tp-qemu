from virttest import utils_misc
from virttest.qemu_devices import qdevices

from provider import job_utils


class StorageVolume(object):

    def __init__(self, pool):
        self.name = None
        self.pool = pool
        self._url = None
        self._path = None
        self._capacity = None
        self._key = None
        self._auth = None
        self._format = None
        self._protocol = None
        self.is_allocated = None
        self.preallocation = None
        self.backing = None
        self.encrypt = None
        self.used_by = []
        self.pool.add_volume(self)
        self._params = None

    @property
    def url(self):
        if self._url is None:
            if self.name and hasattr(self.pool.helper, "get_url_by_name"):
                url = self.pool.helper.get_url_by_name(self.name)
                self._url = url
        return self._url

    @url.setter
    def url(self, url):
        self._url = url

    @property
    def path(self):
        if self._path is None:
            if self.url and hasattr(self.pool.helper, "url_to_path"):
                path = self.pool.helper.url_to_path(self.url)
                self._path = path
        return self._path

    @path.setter
    def path(self, path):
        self._path = path

    @property
    def key(self):
        if self._key is None:
            if self.pool.TYPE in ("directory", "nfs"):
                self._key = self.path
            else:
                self._key = self.url
        return self._key

    @key.setter
    def key(self, key):
        self._key = key

    @property
    def format(self):
        if self._format is None:
            self._format = qdevices.QBlockdevFormatRaw(self.name)
        return self._format

    @format.setter
    def format(self, format):
        if format == "qcow2":
            format_cls = qdevices.QBlockdevFormatQcow2
        else:
            format_cls = qdevices.QBlockdevFormatRaw
        self._format = format_cls(self.name)

    @property
    def protocol(self):
        if self._protocol is None:
            if self.pool.TYPE == "direct-iscsi":
                protocol_cls = qdevices.QBlockdevProtocolIscsi
            elif self.pool.TYPE == "nfs":
                protocol_cls = qdevices.QBlockdevProtocolNfs
            elif self.pool.TYPE == "gluster":
                protocol_cls = qdevices.QBlockdevProtocolGluster
            elif self.pool.TYPE == "rbd":
                protocol_cls = qdevices.QBlockdevProtocolRbd
            else:
                protocol_cls = qdevices.QBlockdevProtocolFile
            node = protocol_cls(self.name)
            self._protocol = node
        return self._protocol

    @property
    def capacity(self):
        if self._capacity is None:
            if self.key and hasattr(self.pool.helper, "get_size"):
                self._capacity = self.pool.get_size(self.key)
        if self._capacity is None:
            self._capacity = 0
        return int(self._capacity)

    @capacity.setter
    def capacity(self, size):
        self._capacity = float(
            utils_misc.normalize_data_size(
                str(size), 'B', '1024'))

    @property
    def auth(self):
        if self._auth is None:
            if self.pool.source:
                self._auth = self.pool.source.auth
        return self._auth

    def refresh_with_params(self, params):
        self._params = params
        self.format = params.get("image_format", "qcow2")
        self.capacity = params.get("image_size", "100M")
        self.preallocation = params.get("preallocation", "off")
        self.refresh_protocol_by_params(params)
        self.refresh_format_by_params(params)

    def refresh_format_by_params(self, params):
        if self.format.TYPE == "qcow2":
            properties = {"lazy_refcounts": int,
                          "pass_discard_request": bool,
                          "pass_discard_snapshot": bool,
                          "pass_discard_other": bool,
                          "overlap_check": bool,
                          "cache_size": int,
                          "l2_cache_size": int,
                          "l2_cache_entry_size": int,
                          "refcount_cache_size": int,
                          "cache_clean_interval": int}
        else:
            properties = {"offset": int}

        arguments = params.copy_from_keys(properties.keys())
        for key, val in arguments.items():
            option_type = properties[key]
            key = key.replace("_", "-")
            if option_type is bool:
                self.format.set_param(key, val, option_type)
            else:
                self.format.set_param(key, val)
        if self.encrypt:
            self.format.set_param(
                "encrypt.key-secret",
                self.encrypt.secret.name)
            self.format.set_param("encrypt.format", self.encrypt.format)

        if self.backing:
            backing_node = self.backing.format.get_param("node-name")
            self.format.set_param("backing", backing_node)
        self.format.set_param("file", self.protocol.get_param("node-name"))

    def refresh_protocol_by_params(self, params):
        if self.protocol.TYPE == "file":
            pr_manager = params.get("pr_manager")
            aio = params.get("image_aio")
            locking = params.get("image_locking")
            drop_cache = params.get("drop_cache")
            check_drop_cache = params.get("check_drop_cache")
            self.protocol.set_param("filename", self.path)
            if pr_manager:
                self.protocol.set_param("pr-manager", pr_manager)
            if aio:
                self.protocol.set_param("aio", aio)
            if drop_cache:
                self.protocol.set_param("drop-cache", drop_cache)
            if check_drop_cache:
                self.protocol.set_param("x-check-drop-cache", check_drop_cache)
            if locking:
                self.protocol.set_param("locking", locking)
        elif self.protocol.TYPE == "nfs":
            self.protocol.set_param('path', self.pool.source.dir_path)
            self.protocol.set_param(
                'server.host', self.pool.source.hosts[0].hostname)
        elif self.protocol.TYPE == "iscsi":
            # asec not support by qemu, now
            self.protocol.set_param('transport', 'tcp')
            self.protocol.set_param('portal', self.pool.helper.portal)
            self.protocol.set_param('target', self.pool.helper.target)
            self.protocol.set_param('lun', self.url.split('/')[-1])
            self.protocol.set_param(
                'initiator-name', self.pool.helper.initiator)
            if self.auth:
                self.protocol.set_param("user", self.auth.username)
                self.protocol.set_param(
                    "password-secret", self.auth.secret.name)

        elif self.protocol.TYPE == "rbd":
            self.protocol.set_param("pool", self.pool.source.name)
            self.protocol.set_param("image", self.path.split("/")[1:])
            if self.auth:
                self.protocol.set_param("user", self.auth.username)
                self.protocol.set_param("key-secret", self.auth.password)
                self.protocol.set_param("auth-client-required", "cephx")

        elif self.protocol.TYPE == "gluster":
            self.protocol.set_param("volume", self.pool.source.name)
            self.protocol.set_param("path", self.path)
            self.protocol.set_param(
                "server.hostname",
                self.pool.source.hosts[0].hostname)
            self.protocol.set_param(
                "server.port", self.pool.source.hosts[0].port)

    def info(self):
        out = dict()
        out["name"] = self.name
        out["pool"] = str(self.pool)
        out["url"] = self.url
        out["path"] = self.path
        out["key"] = self.key
        out["format"] = self.format.TYPE
        out["auth"] = str(self.auth)
        out["capacity"] = self.capacity
        out["preallocation"] = self.preallocation
        out["backing"] = str(self.backing)
        return out

    def generate_qemu_img_options(self):
        options = " -f %s" % self.format.TYPE
        if self.format.TYPE == "qcow2":
            backing_store = self.backing
            if backing_store:
                options += " -b %s" % backing_store.key
            encrypt = self.format.get_param("encrypt")
            if encrypt:
                secret = encrypt.secret
                options += " -%s " % secret.as_qobject().cmdline()
                options += " -o encrypt.format=%s,encrypt.key-secret=%s" % (
                    encrypt.format, secret.name)
        return options

    def hotplug(self, vm):
        protocol_node = self.protocol
        self.create_protocol_by_qmp(vm)
        cmd, options = protocol_node.hotplug_qmp()
        vm.monitor.cmd(cmd, options)
        format_node = self.format
        self.format_protocol_by_qmp(vm)
        cmd, options = format_node.hotplug_qmp()
        vm.monitor.cmd(cmd, options)
        self.pool.refresh()

    def create_protocol_by_qmp(self, vm, timeout=120):
        protocol_node = self.protocol
        node_name = protocol_node.get_param("node-name")
        args = {"driver": self.protocol.TYPE}
        if protocol_node.TYPE == "file":
            args["filename"] = protocol_node.get_param("filename")
            args["size"] = self.capacity
        job_id = "j_%s" % node_name
        vm.monitor.cmd("blockdev-create", {"options": args, "job-id": job_id})
        job_utils.wait_until_job_status_match(vm, "concluded", job_id, timeout)
        vm.monitor.job_dismiss(job_id)

    def format_protocol_by_qmp(self, vm, timeout=120):
        format_node = self.format
        node_name = self.format.get_param("node-name")
        arguments = {"driver": self.format.TYPE,
                     "file": self.protocol.get_param("node-name")}
        if self.backing:
            arguments["backing-fmt"] = format_node.TYPE
            arguments["backing-file"] = self.backing.as_json()
        if self.encrypt:
            arguments["encrypt"] = dict()
            key_secret = self.format.get_param("encrypt.key-secret")
            if key_secret:
                arguments["encrypt"]["key-secret"] = key_secret
            encrypt_format = self.format.get_param("encrypt.format")
            if encrypt_format:
                arguments["encrypt"]["format"] = encrypt_format
        if self._params.get("image_cluster_size"):
            arguments["cluster-size"] = int(self._params["image_cluster_size"])
        arguments["size"] = self.capacity
        job_id = "j_%s" % node_name
        vm.monitor.cmd("blockdev-create",
                       {"options": arguments, "job-id": job_id})
        job_utils.wait_until_job_status_match(vm, "concluded", job_id, timeout)
        vm.monitor.job_dismiss(job_id)

    def __str__(self):
        return "%s-%s(%s)" % (self.__class__.__name__,
                              self.name, str(self.key))

    def __eq__(self, vol):
        if not isinstance(vol, StorageVolume):
            return False
        else:
            return self.info() == vol.info()

    def __hash__(self):
        return hash(str(self.info()))

    def __repr__(self):
        return "'%s'" % self.name

    def as_json(self):
        _, options = self.format.hotplug_qmp()
        return "json: %s" % options
