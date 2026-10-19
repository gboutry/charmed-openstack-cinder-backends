Huawei Storage Backend for Cinder
-------------------------------

Overview
========

This charm provides a Huawei storage backend for use with the Cinder
charm on Ubuntu Jammy / OpenStack Caracal from the UCA. Set
`openstack-origin` to an archive providing `python3-cinder-huawei`; the charm
enables that archive and installs the package. Changing the origin upgrades
the packages when newer versions are available.

For iSCSI, set `default-targetip` to one or more whitespace-separated target
IP addresses. Select multiple target IPs for multipathing. The packaged
driver does not support port-group selection.

To use:

    juju deploy cinder
    juju deploy cinder-huawei-oem
    juju add-relation cinder-huawei-oem cinder

Configuration
=============

See config.yaml for details of configuration options.
