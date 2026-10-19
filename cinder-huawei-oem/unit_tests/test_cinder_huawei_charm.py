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
from src.charm import CinderHuaweiCharm
from ops.model import (
    ActiveStatus,
    BlockedStatus,
)
from ops.testing import Harness
from unittest.mock import patch

TEST_XML_PATH = "/etc/cinder/cinder-huawei-oem/cinder_huawei_conf.xml"


class TestCinderHuaweiCharm(unittest.TestCase):

    def setUp(self):
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
            'cinder.volume.drivers.huawei.huawei_driver.HuaweiISCSIDriver'
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
            'cinder.volume.drivers.huawei.huawei_driver.HuaweiFCDriver'
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
        for option in ('metro_san_user', 'metro_san_password',
                       'metro_domain_name', 'metro_san_address',
                       'metro_storage_pools'):
            self.assertNotIn(option, conf)

    @patch.object(CinderHuaweiCharm, 'create_huawei_conf')
    def test_hypermetro_set(self, mock_create_huawei_conf):
        """Verify all five metro-* options are passed through to
           cinder.conf when they are all set."""
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
        self.assertEqual(conf['metro_san_user'], 'metrouser')
        self.assertEqual(conf['metro_san_password'], 'metropassword')
        self.assertEqual(conf['metro_domain_name'], 'metrodomain')
        self.assertEqual(
            conf['metro_san_address'],
            'https://remote.example.com:8088/deviceManager/rest/')
        self.assertEqual(conf['metro_storage_pools'], 'remotepool')

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
