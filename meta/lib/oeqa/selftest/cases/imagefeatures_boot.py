from oeqa.selftest.case import OESelftestTestCase
from oeqa.core.decorator.oeid import OETestID
from oeqa.utils.commands import runqemu
from oeqa.utils.sshcontrol import SSHControl

class ImageFeaturesBoot(OESelftestTestCase):
    test_user = 'tester'
    root_user = 'root'

    @OETestID(1107)
    def test_non_root_user_can_connect_via_ssh_without_password(self):
        """
        Summary: Check if non root user can connect via ssh without password
        Expected: 1. Connection to the image via ssh using root user without providing a password should be allowed.
                  2. Connection to the image via ssh using tester user without providing a password should be allowed.
        Product: oe-core
        Author: Ionut Chisanovici <ionutx.chisanovici@intel.com>
        AutomatedBy: Daniel Istrate <daniel.alexandrux.istrate@intel.com>
        """

        features = 'EXTRA_IMAGE_FEATURES = "ssh-server-openssh empty-root-password allow-empty-password"\n'
        features += 'INHERIT += "extrausers"\n'
        features += 'EXTRA_USERS_PARAMS = "useradd -p \'\' {}; usermod -s /bin/sh {};"'.format(self.test_user, self.test_user)
        self.write_config(features)

        # Build a core-image-minimal
        self.bitbake('core-image-minimal')

        with runqemu("core-image-minimal") as qemu:
            # Attempt to ssh with each user into qemu with empty password
            for user in [self.root_user, self.test_user]:
                ssh = SSHControl(ip=qemu.ip, logfile=qemu.sshlog, user=user)
                status, output = ssh.run("true")
                self.assertEqual(status, 0, 'ssh to user %s failed with %s' % (user, output))

    @OETestID(1115)
    def test_all_users_can_connect_via_ssh_without_password(self):
        """
        Summary:     Check if all users can connect via ssh without password
        Expected: 1. Connection to the image via ssh using root user without providing a password should NOT be allowed.
                  2. Connection to the image via ssh using tester user without providing a password should be allowed.
        Product:     oe-core
        Author:      Ionut Chisanovici <ionutx.chisanovici@intel.com>
        AutomatedBy: Daniel Istrate <daniel.alexandrux.istrate@intel.com>
        """

        features = 'EXTRA_IMAGE_FEATURES = "ssh-server-openssh allow-empty-password"\n'
        features += 'INHERIT += "extrausers"\n'
        features += 'EXTRA_USERS_PARAMS = "useradd -p \'\' {}; usermod -s /bin/sh {};"'.format(self.test_user, self.test_user)
        self.write_config(features)

        # Build a core-image-minimal
        self.bitbake('core-image-minimal')

        with runqemu("core-image-minimal") as qemu:
            # Attempt to ssh with each user into qemu with empty password
            for user in [self.root_user, self.test_user]:
                ssh = SSHControl(ip=qemu.ip, logfile=qemu.sshlog, user=user)
                status, output = ssh.run("true")
                if user == 'root':
                    self.assertNotEqual(status, 0, 'ssh to user root was allowed when it should not have been')
                else:
                    self.assertEqual(status, 0, 'ssh to user tester failed with %s' % output)
