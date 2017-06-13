import os
import re

from oeqa.selftest.case import OESelftestTestCase
from oeqa.core.decorator.oeid import OETestID
from oeqa.utils.commands import runqemu

class Postinst(OESelftestTestCase):
    @OETestID(1540)
    def test_verify_postinst(self):
        """
        Summary: The purpose of this test is to verify the execution order of postinst Bugzilla ID: [5319]
        Expected :
        1. Compile a minimal image.
        2. The compiled image will add the created layer with the recipes postinst[ abdpt]
        3. Run qemux86
        4. Validate the task execution order
        Author: Francisco Pedraza <francisco.j.pedraza.gonzalez@intel.com>
        """
        features = 'INHERIT += "testimage"\n'
        features += 'CORE_IMAGE_EXTRA_INSTALL += "postinst-at-rootfs \
postinst-delayed-a \
postinst-delayed-b \
postinst-delayed-d \
postinst-delayed-p \
postinst-delayed-t \
"\n'
        self.write_config(features)

        self.bitbake('core-image-minimal -f ')

        postinst_list = ['100-postinst-at-rootfs',
                         '101-postinst-delayed-a',
                         '102-postinst-delayed-b',
                         '103-postinst-delayed-d',
                         '104-postinst-delayed-p',
                         '105-postinst-delayed-t']
        path_workdir = self.get_bb_var('WORKDIR','core-image-minimal')
        workspacedir = 'testimage/qemu_boot_log'
        workspacedir = os.path.join(path_workdir, workspacedir)
        rexp = re.compile("^Running postinst .*/(?P<postinst>.*)\.\.\.$")
        with runqemu('core-image-minimal') as qemu:
            with open(workspacedir) as f:
                found = False
                idx = 0
                for line in f.readlines():
                    line = line.strip().replace("^M","")
                    if not line: # To avoid empty lines
                        continue
                    m = rexp.search(line)
                    if m:
                        self.assertEqual(postinst_list[idx], m.group('postinst'), "Fail")
                        idx = idx+1
                        found = True
                    elif found:
                        self.assertEqual(idx, len(postinst_list), "Not found all postinsts")
                        break

    @OETestID(1545)
    def test_postinst_rootfs_and_boot(self):
        """
        Summary:        The purpose of this test case is to verify Post-installation
                        scripts are called when rootfs is created and also test
                        that script can be delayed to run at first boot.
        Dependencies:   NA
        Steps:          1. Add proper configuration to local.conf file
                        2. Build a "core-image-minimal" image
                        3. Verify that file created by postinst_rootfs recipe is
                           present on rootfs dir.
                        4. Boot the image created on qemu and verify that the file
                           created by postinst_boot recipe is present on image.
        Expected:       The files are successfully created during rootfs and boot
                        time for 3 different package managers: rpm,ipk,deb and
                        for initialization managers: sysvinit and systemd.

        """
        file_rootfs_name = "this-was-created-at-rootfstime"
        fileboot_name = "this-was-created-at-first-boot"
        rootfs_pkg = 'postinst-at-rootfs'
        boot_pkg = 'postinst-delayed-a'
        #Step 1
        common_features = 'MACHINE = "qemux86"\n'
        common_features += 'CORE_IMAGE_EXTRA_INSTALL += "%s %s "\n'% (rootfs_pkg, boot_pkg)
        common_features += 'IMAGE_FEATURES += "ssh-server-openssh"\n'
        for init_manager in ("sysvinit", "systemd"):
            #for sysvinit no extra configuration is needed,
            features = ''
            if (init_manager is "systemd"):
                features += 'DISTRO_FEATURES_append = " systemd"\n'
                features += 'VIRTUAL-RUNTIME_init_manager = "systemd"\n'
                features += 'DISTRO_FEATURES_BACKFILL_CONSIDERED = "sysvinit"\n'
                features += 'VIRTUAL-RUNTIME_initscripts = ""\n'
            for classes in ("package_rpm package_deb package_ipk",
                            "package_deb package_rpm package_ipk",
                            "package_ipk package_deb package_rpm"):
                features += 'PACKAGE_CLASSES = "%s"\n' % classes
                self.write_config(common_features + features)

                #Step 2
                self.bitbake('core-image-minimal')

                #Step 3
                file_rootfs_created = os.path.join(self.get_bb_var('IMAGE_ROOTFS',"core-image-minimal"),
                                                   file_rootfs_name)
                found = os.path.isfile(file_rootfs_created)
                self.assertTrue(found, "File %s was not created at rootfs time by %s" % \
                                (file_rootfs_name, rootfs_pkg))

                #Step 4
                testcommand = 'ls /etc/'+fileboot_name
                with runqemu('core-image-minimal') as qemu:
                    sshargs = '-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no'
                    result = self.runCmd('ssh %s root@%s %s' % (sshargs, qemu.ip, testcommand))
                    self.assertEqual(result.status, 0, 'File %s was not created at firts boot'% fileboot_name)
