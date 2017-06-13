import os

from oeqa.selftest.case import OESelftestTestCase
from oeqa.utils.commands import runqemu
from oeqa.core.decorator.oeid import OETestID

class TestExport(OESelftestTestCase):
    @classmethod
    def tearDownClass(cls):
        cls.runCmd("rm -rf /tmp/sdk")
        super(TestExport, cls).tearDownClass()

    @OETestID(1499)
    def test_testexport_basic(self):
        """
        Summary: Check basic testexport functionality with only ping test enabled.
        Expected: 1. testexport directory must be created.
                  2. runexported.py must run without any error/exception.
                  3. ping test must succeed.
        Product: oe-core
        Author: Mariano Lopez <mariano.lopez@intel.com>
        """

        features = 'INHERIT += "testexport"\n'
        # These aren't the actual IP addresses but testexport class needs something defined
        features += 'TEST_SERVER_IP = "192.168.7.1"\n'
        features += 'TEST_TARGET_IP = "192.168.7.1"\n'
        features += 'TEST_SUITES = "ping"\n'
        self.write_config(features)

        # Build tesexport for core-image-minimal
        self.bitbake('core-image-minimal')
        self.bitbake('-c testexport core-image-minimal')

        testexport_dir = self.get_bb_var('TEST_EXPORT_DIR', 'core-image-minimal')

        # Verify if TEST_EXPORT_DIR was created
        isdir = os.path.isdir(testexport_dir)
        self.assertEqual(True, isdir, 'Failed to create testexport dir: %s' % testexport_dir)

        with runqemu('core-image-minimal') as qemu:
            # Attempt to run runexported.py to perform ping test
            test_path = os.path.join(testexport_dir, "oe-test")
            data_file = os.path.join(testexport_dir, 'data', 'testdata.json')
            manifest = os.path.join(testexport_dir, 'data', 'manifest')
            cmd = ("%s runtime --test-data-file %s --packages-manifest %s "
                   "--target-ip %s --server-ip %s --quiet"
                  % (test_path, data_file, manifest, qemu.ip, qemu.server_ip))
            result = self.runCmd(cmd)
            # Verify ping test was succesful
            self.assertEqual(0, result.status, 'oe-test runtime returned a non 0 status')

    @OETestID(1641)
    def test_testexport_sdk(self):
        """
        Summary: Check sdk functionality for testexport.
        Expected: 1. testexport directory must be created.
                  2. SDK tarball must exists.
                  3. Uncompressing of tarball must succeed.
                  4. Check if the SDK directory is added to PATH.
                  5. Run tar from the SDK directory.
        Product: oe-core
        Author: Mariano Lopez <mariano.lopez@intel.com>
        """

        features = 'INHERIT += "testexport"\n'
        # These aren't the actual IP addresses but testexport class needs something defined
        features += 'TEST_SERVER_IP = "192.168.7.1"\n'
        features += 'TEST_TARGET_IP = "192.168.7.1"\n'
        features += 'TEST_SUITES = "ping"\n'
        features += 'TEST_EXPORT_SDK_ENABLED = "1"\n'
        features += 'TEST_EXPORT_SDK_PACKAGES = "nativesdk-tar"\n'
        self.write_config(features)

        # Build tesexport for core-image-minimal
        self.bitbake('core-image-minimal')
        self.bitbake('-c testexport core-image-minimal')

        needed_vars = ['TEST_EXPORT_DIR', 'TEST_EXPORT_SDK_DIR', 'TEST_EXPORT_SDK_NAME']
        bb_vars = self.get_bb_vars(needed_vars, 'core-image-minimal')
        testexport_dir = bb_vars['TEST_EXPORT_DIR']
        sdk_dir = bb_vars['TEST_EXPORT_SDK_DIR']
        sdk_name = bb_vars['TEST_EXPORT_SDK_NAME']

        # Check for SDK
        tarball_name = "%s.sh" % sdk_name
        tarball_path = os.path.join(testexport_dir, sdk_dir, tarball_name)
        msg = "Couldn't find SDK tarball: %s" % tarball_path
        self.assertEqual(os.path.isfile(tarball_path), True, msg)

        # Extract SDK and run tar from SDK
        result = self.runCmd("%s -y -d /tmp/sdk" % tarball_path)
        self.assertEqual(0, result.status, "Couldn't extract SDK")

        env_script = result.output.split()[-1]
        result = self.runCmd(". %s; which tar" % env_script, shell=True)
        self.assertEqual(0, result.status, "Couldn't setup SDK environment")
        is_sdk_tar = True if "/tmp/sdk" in result.output else False
        self.assertTrue(is_sdk_tar, "Couldn't setup SDK environment")

        tar_sdk = result.output
        result = self.runCmd("%s --version" % tar_sdk)
        self.assertEqual(0, result.status, "Couldn't run tar from SDK")

