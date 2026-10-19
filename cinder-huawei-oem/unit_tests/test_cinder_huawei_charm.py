# Copyright 2016 Canonical Ltd
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

import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

from jinja2 import Environment, FileSystemLoader
from src.charm import CinderHuaweiCharm
from ops.model import (
    ActiveStatus,
    BlockedStatus,
)
from ops.testing import Harness
from unittest.mock import Mock, call, patch

TEST_XML_PATH = "/etc/cinder/cinder-huawei-oem/cinder_huawei_conf.xml"
VALID_CONFIG = {
    'product': 'Dorado',
    'username': 'myuser',
    'password': 'mypassword',
    'storage-pool': 'mystoragepool',
    'rest-url': 'https://example.com:8088/deviceManager/rest/',
    'default-targetip': '192.0.2.10',
}


class TestCinderHuaweiCharm(unittest.TestCase):

    def setUp(self):
        self.package_ops = Mock()
        for name in ('configure_installation_source', 'apt_update',
                     'apt_install'):
            patcher = patch('src.charm.' + name)
            self.package_ops.attach_mock(patcher.start(), name)
            self.addCleanup(patcher.stop)
        self.harness = Harness(CinderHuaweiCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.harness.set_leader(True)
        backend = self.harness.add_relation('storage-backend', 'cinder')
        self.harness.add_relation_unit(backend, 'cinder/0')

    def test_cinder_base(self):
        self.assertEqual(
            self.harness.framework.model.app.name,
            'cinder-huawei-oem')
        # Test that charm is blocked because of missing configurations.
        self.harness.update_config({})
        self.assertTrue(isinstance(
            self.harness.model.unit.status, BlockedStatus))

    @patch.object(CinderHuaweiCharm, 'create_huawei_conf')
    def test_multipath_config(self, mock_create_huawei_conf):
        self.harness.update_config({'use-multipath': True})
        mock_create_huawei_conf.return_value = TEST_XML_PATH
        conf = dict(self.harness.charm.cinder_configuration(
            dict(self.harness.model.config)))
        self.assertTrue(conf.get('use_multipath_for_image_xfer'))
        self.assertTrue(conf.get('enforce_multipath_for_image_xfer'))

    @patch.object(CinderHuaweiCharm, 'create_huawei_conf')
    def test_cinder_configuration(self, mock_create_huawei_conf):
        mock_create_huawei_conf.return_value = TEST_XML_PATH
        test_config = {
            'protocol': 'iscsi',
            'product': 'Dorado',
            'username': 'myuser',
            'password': 'mypassword',
            'storage-pool': 'mystoragepool',
            'default-targetip': '192.0.2.10',
            'rest-url': 'https://example.com:8088/deviceManager/rest/',
            'volume-backend-name': 'huawei_dorado_iscsi',
        }
        self.harness.model.config
        self.harness.update_config(test_config)
        conf = dict(self.harness.charm.cinder_configuration(
            dict(self.harness.model.config)))
        self.assertTrue(isinstance(
            self.harness.model.unit.status, ActiveStatus))
        self.assertEqual(conf['volume_backend_name'], 'huawei_dorado_iscsi')
        self.assertEqual(
            conf['volume_driver'],
            'huawei_cinder.huawei_driver.HuaweiISCSIDriver'
        )
        self.assertEqual(
            conf['cinder_huawei_conf_file'],
            TEST_XML_PATH
        )

    @patch.object(CinderHuaweiCharm, 'create_huawei_conf')
    def test_cinder_configuration_fc(self, mock_create_huawei_conf):
        mock_create_huawei_conf.return_value = TEST_XML_PATH
        test_config = {
            'protocol': 'fc',
            'product': 'Dorado',
            'username': 'myuser',
            'password': 'mypassword',
            'storage-pool': 'mystoragepool',
            'rest-url': 'https://example.com:8088/deviceManager/rest/',
            'volume-backend-name': 'huawei_dorado_fc',
        }
        self.harness.model.config
        self.harness.update_config(test_config)
        conf = dict(self.harness.charm.cinder_configuration(
            dict(self.harness.model.config)))
        self.assertTrue(isinstance(
            self.harness.model.unit.status, ActiveStatus))
        self.assertEqual(conf['volume_backend_name'], 'huawei_dorado_fc')
        self.assertEqual(
            conf['volume_driver'],
            'huawei_cinder.huawei_driver.HuaweiFCDriver'
        )
        self.assertEqual(
            conf['cinder_huawei_conf_file'],
            TEST_XML_PATH
        )

    def test_xml_escaping_special_characters(self):
        """Verify that special characters in config are escaped for XML."""
        # Test config with characters that must be escaped in XML
        test_config = {
            'username': 'admin&user',
            'password': 'Pass<word>&&&e',
            'product': 'Storage<b>',
            'rest-url': 'https://api.com?query=1&id=2',
            'storage-pool': 'mystoragepool',
        }

        context = self.harness.charm.get_huawei_context(test_config)
        # & becomes &amp; < becomes &lt; > becomes &gt;
        self.assertEqual(context['username'], 'admin&amp;user')
        self.assertEqual(
            context['password'],
            'Pass&lt;word&gt;&amp;&amp;&amp;e',
        )
        self.assertEqual(context['product'], 'Storage&lt;b&gt;')
        self.assertEqual(
            context['rest_url'],
            'https://api.com?query=1&amp;id=2',
        )

    def test_blocked_on_invalid_protocol(self):
        """Verify charm blocks when an unsupported protocol is provided."""
        test_config = {
            'protocol': 'invalid-protocol',  # Not 'iscsi' or 'fc'
            'product': 'Dorado',
            'username': 'myuser',
            'password': 'mypassword',
            'storage-pool': 'mystoragepool',
            'rest-url': 'https://example.com:8088/deviceManager/rest/',
            'luntype': 'Thin'
        }
        self.harness.update_config(test_config)

        self.assertTrue(isinstance(
            self.harness.model.unit.status,
            BlockedStatus
        ))
        self.assertIn(
            "Invalid protocol",
            self.harness.model.unit.status.message
        )

    def test_blocked_on_invalid_luntype(self):
        """Verify charm blocks when luntype is not Thin or Thick.
           Particularly tricky as the storage driver doesn't
           provide a clear message as it is case sensitive."""
        test_config = {
            'protocol': 'iscsi',
            'product': 'Dorado',
            'username': 'myuser',
            'password': 'mypassword',
            'storage-pool': 'mystoragepool',
            'rest-url': 'https://example.com:8088/deviceManager/rest/',
            'luntype': 'thin',  # Lowercase 't' should be invalid
        }
        self.harness.update_config(test_config)

        self.assertTrue(isinstance(
            self.harness.model.unit.status,
            BlockedStatus
        ))
        self.assertIn(
            "Invalid luntype",
            self.harness.model.unit.status.message
        )

    @patch.object(CinderHuaweiCharm, 'create_huawei_conf')
    def test_active_on_valid_luntype(self, mock_create_huawei_conf):
        """Verify charm is active when luntype is set to Thin or Thick"""
        mock_create_huawei_conf.return_value = TEST_XML_PATH
        test_config = {
            'protocol': 'iscsi',
            'product': 'Dorado',
            'username': 'myuser',
            'password': 'mypassword',
            'storage-pool': 'mystoragepool',
            'default-targetip': '192.0.2.10',
            'rest-url': 'https://example.com:8088/deviceManager/rest/',
            'volume-backend-name': 'huawei_dorado_iscsi',
            'luntype': 'Thin',
        }
        self.harness.update_config(test_config)
        self.assertTrue(isinstance(
            self.harness.model.unit.status,
            ActiveStatus
        ))

    @patch.object(CinderHuaweiCharm, 'create_huawei_conf')
    def test_hypermetro_unset(self, mock_create_huawei_conf):
        """Verify HyperMetro is opt-in: with no metro-* option set the charm
           is active and emits no metro_* options."""
        mock_create_huawei_conf.return_value = TEST_XML_PATH
        test_config = {
            'protocol': 'iscsi',
            'product': 'Dorado',
            'username': 'myuser',
            'password': 'mypassword',
            'storage-pool': 'mystoragepool',
            'default-targetip': '192.0.2.10',
            'rest-url': 'https://example.com:8088/deviceManager/rest/',
            'luntype': 'Thin',
        }
        self.harness.update_config(test_config)
        self.assertTrue(isinstance(
            self.harness.model.unit.status,
            ActiveStatus
        ))
        conf = dict(self.harness.charm.cinder_configuration(
            dict(self.harness.model.config)))
        self.assertNotIn('hypermetro_device', conf)
        for option in ('metro_san_user', 'metro_san_password',
                       'metro_domain_name', 'metro_san_address',
                       'metro_storage_pools'):
            self.assertNotIn(option, conf)

    @patch.object(CinderHuaweiCharm, 'create_huawei_conf')
    def test_hypermetro_set(self, mock_create_huawei_conf):
        """Verify all five metro-* options form hypermetro_device."""
        mock_create_huawei_conf.return_value = TEST_XML_PATH
        test_config = {
            'protocol': 'fc',
            'product': 'Dorado',
            'username': 'myuser',
            'password': 'mypassword',
            'storage-pool': 'mystoragepool',
            'rest-url': 'https://example.com:8088/deviceManager/rest/',
            'luntype': 'Thin',
            'fc-hostname': 'compute.*',
            'metro-san-user': 'metrouser',
            'metro-san-password': 'metropassword',
            'metro-domain-name': 'metrodomain',
            'metro-san-address':
                'https://remote.example.com:8088/deviceManager/rest/',
            'metro-storage-pool': 'remotepool',
        }
        self.harness.update_config(test_config)
        self.assertTrue(isinstance(
            self.harness.model.unit.status,
            ActiveStatus
        ))
        conf = dict(self.harness.charm.cinder_configuration(
            dict(self.harness.model.config)))
        self.assertEqual(
            conf['hypermetro_device'],
            'san_user:metrouser,san_password:metropassword,'
            'metro_domain:metrodomain,'
            'san_address:https://remote.example.com:8088/deviceManager/rest/,'
            'storage_pool:remotepool')
        for option in ('metro_san_user', 'metro_san_password',
                       'metro_domain_name', 'metro_san_address',
                       'metro_storage_pools'):
            self.assertNotIn(option, conf)

    @patch.object(CinderHuaweiCharm, 'create_huawei_conf')
    def test_blocked_on_partial_hypermetro(self, mock_create_huawei_conf):
        """Verify a partial metro-* configuration blocks, names the missing
           options, and is not published to the principal charm."""
        mock_create_huawei_conf.return_value = TEST_XML_PATH
        test_config = {
            'protocol': 'iscsi',
            'product': 'Dorado',
            'username': 'myuser',
            'password': 'mypassword',
            'storage-pool': 'mystoragepool',
            'rest-url': 'https://example.com:8088/deviceManager/rest/',
            'luntype': 'Thin',
            'metro-san-user': 'metrouser',
        }
        self.harness.update_config(test_config)

        self.assertTrue(isinstance(
            self.harness.model.unit.status,
            BlockedStatus
        ))
        message = self.harness.model.unit.status.message
        self.assertIn('HyperMetro partially configured', message)
        for option in ('metro-san-password', 'metro-domain-name',
                       'metro-san-address', 'metro-storage-pool'):
            self.assertIn(option, message)

        relation = self.harness.model.get_relation('storage-backend')
        relation_data = self.harness.get_relation_data(
            relation.id, self.harness.model.unit.name)
        self.assertNotIn('subordinate_configuration', relation_data)

    @patch.object(CinderHuaweiCharm, 'create_huawei_conf')
    def test_blocked_on_multiple_metro_storage_pool(
            self, mock_create_huawei_conf):
        """Verify charm blocks when metro-storage-pool is given a
           semicolon(;) separated list: unlike storage-pool the driver
           compares it for exact equality against a single remote pool."""
        mock_create_huawei_conf.return_value = TEST_XML_PATH
        test_config = {
            'protocol': 'iscsi',
            'product': 'Dorado',
            'username': 'myuser',
            'password': 'mypassword',
            'storage-pool': 'mystoragepool',
            'rest-url': 'https://example.com:8088/deviceManager/rest/',
            'luntype': 'Thin',
            'metro-san-user': 'metrouser',
            'metro-san-password': 'metropassword',
            'metro-domain-name': 'metrodomain',
            'metro-san-address':
                'https://remote.example.com:8088/deviceManager/rest/',
            'metro-storage-pool': 'pool1;pool2',
        }
        self.harness.update_config(test_config)

        self.assertTrue(isinstance(
            self.harness.model.unit.status,
            BlockedStatus
        ))
        self.assertIn(
            'metro-storage-pool only supports a single pool name',
            self.harness.model.unit.status.message)

    @patch.object(CinderHuaweiCharm, 'create_huawei_conf')
    def test_blocked_on_hypermetro_comma(self, mock_create_huawei_conf):
        mock_create_huawei_conf.return_value = TEST_XML_PATH
        self.harness.update_config({
            'protocol': 'fc',
            'product': 'Dorado',
            'username': 'myuser',
            'password': 'mypassword',
            'storage-pool': 'mystoragepool',
            'rest-url': 'https://example.com:8088/deviceManager/rest/',
            'metro-san-user': 'metrouser',
            'metro-san-password': 'secret,withcomma',
            'metro-domain-name': 'metrodomain',
            'metro-san-address': 'https://remote.example.com/rest/',
            'metro-storage-pool': 'remotepool',
        })
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)
        self.assertIn('metro-san-password',
                      self.harness.model.unit.status.message)
        relation = self.harness.model.get_relation('storage-backend')
        data = self.harness.get_relation_data(
            relation.id, self.harness.model.unit.name)
        self.assertNotIn('subordinate_configuration', data)

    def test_rendered_downstream_xml(self):
        env = Environment(loader=FileSystemLoader(
            Path(__file__).resolve().parents[1] / 'templates'))
        for protocol, expected in [('iscsi', 'iSCSI'), ('fc', 'FC')]:
            with self.subTest(protocol=protocol):
                config = dict(self.harness.model.config)
                config.update({
                    'protocol': protocol,
                    'product': 'Dorado',
                    'username': 'admin&user',
                    'password': 'secret<&',
                    'fc-hostname': 'compute.*&"test',
                    'initiator-name': 'iqn.example:&"test',
                })
                rendered = env.get_template('cinder_huawei_conf.xml').render(
                    self.harness.charm.get_huawei_context(config))
                root = ET.fromstring(rendered)
                self.assertEqual(root.findtext('Storage/Protocol'), expected)
                self.assertEqual(root.findtext('Storage/UserName'),
                                 'admin&user')
                self.assertEqual(root.findtext('Storage/UserPassword'),
                                 'secret<&')
                if protocol == 'fc':
                    initiator = root.find('FC/Initiator')
                    self.assertEqual(initiator.get('HostName'),
                                     config['fc-hostname'])
                    self.assertNotIn('Name', initiator.attrib)
                else:
                    initiator = root.find('iSCSI/Initiator')
                    self.assertEqual(initiator.get('Name'),
                                     config['initiator-name'])
                    self.assertNotIn('TargetPortGroup', initiator.attrib)
                    self.assertIsNone(root.find('iSCSI/DefaultTargetIP'))

    def test_fc_without_hostname(self):
        env = Environment(loader=FileSystemLoader(
            Path(__file__).resolve().parents[1] / 'templates'))
        config = dict(self.harness.model.config)
        config['protocol'] = 'fc'
        rendered = env.get_template('cinder_huawei_conf.xml').render(
            self.harness.charm.get_huawei_context(config))
        self.assertIsNone(ET.fromstring(rendered).find('FC/Initiator'))

    @patch('src.charm.render')
    @patch('src.charm.mkdir')
    def test_xml_credentials_are_private(self, mock_mkdir, mock_render):
        self.harness.charm.create_huawei_conf(dict(self.harness.model.config))
        self.assertEqual(mock_render.call_args.kwargs['perms'], 0o600)
        self.assertEqual(mock_render.call_args.kwargs['owner'], 'cinder')

    def test_install_from_ppa(self):
        self.harness.disable_hooks()
        self.harness.update_config({'openstack-origin': 'ppa:example/drivers'})
        self.harness.enable_hooks()
        self.harness.charm.on.install.emit()
        self.assertEqual(self.package_ops.mock_calls, [
            call.configure_installation_source('ppa:example/drivers'),
            call.apt_update(fatal=True),
            call.apt_install(
                ['cinder-common', 'sysfsutils', 'python3-cinder-huawei'],
                fatal=True),
        ])
        self.assertEqual(self.harness.charm._stored.package_origin,
                         'ppa:example/drivers')

    def test_default_origin(self):
        self.harness.charm.on.install.emit()
        self.package_ops.configure_installation_source.assert_called_once_with(
            'ppa:canonical-openstack/storage-drivers-oem-caracal-updates')
        self.assertEqual(
            self.harness.charm._stored.package_origin,
            'ppa:canonical-openstack/storage-drivers-oem-caracal-updates')

    def test_origin_change_upgrades_packages(self):
        self.harness.charm.on.install.emit()
        self.package_ops.reset_mock()
        self.harness.update_config({'openstack-origin': 'ppa:example/drivers'})
        self.assertEqual(self.package_ops.mock_calls, [
            call.configure_installation_source('ppa:example/drivers'),
            call.apt_update(fatal=True),
            call.apt_install(CinderHuaweiCharm.PACKAGES, fatal=True),
        ])
        self.assertEqual(self.harness.charm._stored.package_origin,
                         'ppa:example/drivers')
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)
        self.assertIn('Missing option(s)',
                      self.harness.model.unit.status.message)

    @patch.object(CinderHuaweiCharm, 'create_huawei_conf')
    def test_unchanged_origin_does_not_reinstall(self, mock_create):
        mock_create.return_value = TEST_XML_PATH
        self.harness.charm.on.install.emit()
        self.package_ops.reset_mock()
        self.harness.update_config({
            'product': 'Dorado',
            'username': 'myuser',
            'password': 'mypassword',
            'storage-pool': 'mystoragepool',
            'default-targetip': '192.0.2.10',
            'rest-url': 'https://example.com:8088/deviceManager/rest/',
        })
        self.harness.update_config({'use-multipath': False})
        self.assertEqual(self.package_ops.mock_calls, [])
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

    def test_failed_origin_change_is_retried(self):
        self.harness.charm.on.install.emit()
        self.package_ops.reset_mock()
        self.package_ops.apt_install.side_effect = RuntimeError('APT failed')
        with self.assertRaisesRegex(RuntimeError, 'APT failed'):
            self.harness.update_config({
                'openstack-origin': 'ppa:example/drivers'})
        self.assertEqual(
            self.harness.charm._stored.package_origin,
            'ppa:canonical-openstack/storage-drivers-oem-caracal-updates')
        self.package_ops.apt_install.side_effect = None
        self.harness.update_config({})
        self.assertEqual(self.package_ops.apt_install.call_count, 2)
        self.assertEqual(self.harness.charm._stored.package_origin,
                         'ppa:example/drivers')

    def test_blocked_on_invalid_iscsi_targets(self):
        for targets in ('', '  ', 'invalid', '192.0.2.999',
                        '192.0.2.10;192.0.2.11'):
            with self.subTest(targets=targets):
                self.harness.update_config(dict(
                    VALID_CONFIG, **{'default-targetip': targets}))
                self.assertIsInstance(self.harness.model.unit.status,
                                      BlockedStatus)
                self.assertIn('default-targetip',
                              self.harness.model.unit.status.message)
                relation = self.harness.model.get_relation(
                    'storage-backend')
                data = self.harness.get_relation_data(
                    relation.id, self.harness.model.unit.name)
                self.assertNotIn('subordinate_configuration', data)

    @patch.object(CinderHuaweiCharm, 'create_huawei_conf')
    def test_valid_iscsi_target_addresses(self, mock_create):
        mock_create.return_value = TEST_XML_PATH
        self.harness.update_config(dict(
            VALID_CONFIG,
            **{'default-targetip': '192.0.2.10 2001:db8::10'}))
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

    def test_target_portgroup_is_not_exposed(self):
        self.assertNotIn('target-portgroup', self.harness.model.config)
        with self.assertRaisesRegex(ValueError,
                                    'unknown config option.*target-portgroup'):
            self.harness.update_config({'target-portgroup': 'my-port-group'})

    @patch.object(CinderHuaweiCharm, 'create_huawei_conf')
    def test_default_volume_backend_name(self, mock_create):
        mock_create.return_value = TEST_XML_PATH
        for value in (None, ''):
            with self.subTest(value=value):
                config = dict(self.harness.model.config)
                config['volume-backend-name'] = value
                options = dict(self.harness.charm.cinder_configuration(config))
                self.assertEqual(options['volume_backend_name'],
                                 self.harness.model.app.name)
