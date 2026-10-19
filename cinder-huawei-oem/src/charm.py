#! /usr/bin/env python3

# Copyright 2021 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


# import base64
import os
import ipaddress
import logging
from xml.sax.saxutils import escape

from ops_openstack.plugins.classes import CinderStoragePluginCharm
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus
from charmhelpers.core.templating import render
from charmhelpers.core.host import mkdir
from charmhelpers.contrib.openstack.utils import configure_installation_source
from charmhelpers.fetch import apt_install, apt_update


logger = logging.getLogger(__name__)

HUAWEI_CNF_FILE = "cinder_huawei_conf.xml"
DRIVER_ISCSI = "huawei_cinder.huawei_driver.HuaweiISCSIDriver"
DRIVER_FC = "huawei_cinder.huawei_driver.HuaweiFCDriver"


class CinderHuaweiCharm(CinderStoragePluginCharm):

    PACKAGES = ['cinder-common', 'sysfsutils', 'python3-cinder-huawei']
    MANDATORY_CONFIG = [
        'protocol',
        'product',
        'username',
        'password',
        'storage-pool',
        'rest-url',
    ]

    """
    The packaged driver consumes remote storage settings through the
    hypermetro_device dictionary. Preserve the existing charm option names
    while translating them to the downstream driver's dictionary keys.
    """
    HYPERMETRO_CONFIG_MAP = {
        'san_user': 'metro-san-user',
        'san_password': 'metro-san-password',
        'metro_domain': 'metro-domain-name',
        'san_address': 'metro-san-address',
        'storage_pool': 'metro-storage-pool',
    }

    # Overriden from the parent. May be set depending on the charm's properties
    stateless = True
    active_active = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stored.set_default(package_origin=None)

    def install_pkgs(self):
        origin = self.config['openstack-origin']
        configure_installation_source(origin)
        apt_update(fatal=True)
        apt_install(self.PACKAGES, fatal=True)
        self._stored.package_origin = origin
        self.update_status()

    def on_install(self, event):
        self.install_pkgs()

    def _on_config(self, event):
        if self._stored.package_origin != self.config['openstack-origin']:
            self.install_pkgs()
        super()._on_config(event)

    def cinder_configuration(self, config):
        # Return the configuration to be set by the principal.
        backend_name = (config.get('volume-backend-name') or
                        self.framework.model.app.name)

        huawei_conf_file = self.create_huawei_conf(config)

        # Set volume_driver
        protocol = self.config.get("protocol")
        if protocol == "iscsi":
            volume_driver = DRIVER_ISCSI
        elif protocol == "fc":
            volume_driver = DRIVER_FC
        logger.debug("Using volume_driver=%s", volume_driver)

        # Set all confs
        options = [
            ('volume_driver', volume_driver),
            ('volume_backend_name', backend_name),
            ("cinder_huawei_conf_file", huawei_conf_file)
        ]

        if config.get('use-multipath'):
            options.extend([
                ('use_multipath_for_image_xfer', True),
                ('enforce_multipath_for_image_xfer', True)
            ])

        hypermetro = ','.join(
            '{}:{}'.format(driver_opt, config[charm_opt])
            for driver_opt, charm_opt in self.HYPERMETRO_CONFIG_MAP.items()
            if config.get(charm_opt))
        if hypermetro:
            options.append(('hypermetro_device', hypermetro))

        return options

    def on_config(self, event):
        config = dict(self.framework.model.config)

        protocol = config.get('protocol')
        luntype = config.get('luntype')
        copy_speed = config.get('lun-copy-speed')

        if protocol not in ['iscsi', 'fc']:
            self.unit.status = BlockedStatus(
                f"Invalid protocol: {protocol}. Must be 'iscsi' or 'fc'"
            )
            return

        if luntype not in ['Thin', 'Thick']:
            self.unit.status = BlockedStatus(
                f"Invalid luntype: {luntype}. Must be 'Thin' or 'Thick'"
            )
            return

        # The driver validates these against ('1', '2', '3', '4') and raises
        # InvalidInput on anything else, which stops the backend starting.
        if copy_speed not in [1, 2, 3, 4]:
            self.unit.status = BlockedStatus(
                f"Invalid lun-copy-speed: {copy_speed}. Must be 1, 2, 3 or 4"
            )
            return

        hypermetro_error = self.check_hypermetro(config)
        if hypermetro_error:
            self.unit.status = BlockedStatus(hypermetro_error)
            return

        if protocol == 'iscsi':
            targets = (config.get('default-targetip') or '').split()
            try:
                if not targets:
                    raise ValueError('no target IPs')
                for target in targets:
                    ipaddress.ip_address(target)
            except ValueError:
                self.unit.status = BlockedStatus(
                    'default-targetip must contain whitespace-separated '
                    'IPv4 or IPv6 addresses for iSCSI')
                return

        app_name = self.framework.model.app.name
        for relation in self.framework.model.relations.get('storage-backend'):
            self.set_data(relation.data[self.unit], config, app_name)
        self._stored.is_started = True
        self.unit.status = ActiveStatus('Unit is ready')

    def check_hypermetro(self, config):
        """Return an error message if the HyperMetro config is unusable.
        """
        options = self.HYPERMETRO_CONFIG_MAP.values()
        missing = sorted(opt for opt in options if not config.get(opt))

        if len(missing) == len(self.HYPERMETRO_CONFIG_MAP):
            return None

        if missing:
            return (
                'HyperMetro partially configured, missing: {}. Set all of '
                'the metro-* options, or none to disable HyperMetro.'.format(
                    ', '.join(missing))
            )

        invalid = sorted(opt for opt in options if ',' in config[opt])
        if invalid:
            return (
                'HyperMetro options cannot contain commas because they are '
                'encoded as hypermetro_device: {}'.format(', '.join(invalid))
            )

        if ';' in config['metro-storage-pool']:
            return (
                'metro-storage-pool only supports a single pool name '
                '(unlike storage-pool, it cannot be a semicolon(;) '
                'separated list)'
            )

        return None

    def get_huawei_context(self, cfg):
        """Returns a rendered huawer conf file"""
        huaweicontext = {
            'protocol': cfg.get('protocol'),
            'product': escape(str(cfg.get('product') or '')),
            'username': escape(str(cfg.get('username') or '')),
            'password': escape(str(cfg.get('password') or '')),
            'rest_url': escape(str(cfg.get('rest-url') or '')),
            'storage_pool': escape(str(cfg.get('storage-pool') or '')),
            'luntype': cfg.get('luntype'),
            'lun_clone_mode': cfg.get('lun-clone-mode'),
            'lun_copy_speed': cfg.get('lun-copy-speed'),
            'default_targetip': cfg.get('default-targetip') or '',
            'initiator_name': cfg.get('initiator-name') or '',
            'fc_hostname': cfg.get('fc-hostname') or '',
            'fc_minonlinefcinitiator': cfg.get('fc-minonlinefcinitiator'),
            'alua': cfg.get('alua'),
            'failovermode': cfg.get('failover-mode'),
            'pathtype': cfg.get('path-type')
        }
        return huaweicontext

    def create_huawei_conf(self, cfg):
        # Set huawei_conf_file path
        huawei_conf_file = os.path.join(
            "/etc/cinder",
            self.framework.model.app.name,
            HUAWEI_CNF_FILE
        )
        # Create dir for huawei storage backend driver
        mkdir(os.path.dirname(huawei_conf_file), owner='cinder')
        # Render huawei_conf_file(XML)
        render(HUAWEI_CNF_FILE, huawei_conf_file,
               self.get_huawei_context(cfg),
               owner='cinder',
               perms=0o600)
        return huawei_conf_file


if __name__ == '__main__':
    main(CinderHuaweiCharm)
