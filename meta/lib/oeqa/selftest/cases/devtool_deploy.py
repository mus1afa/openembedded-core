import os
import tempfile

from oeqa.selftest.cases import devtool
from oeqa.core.decorator.oeid import OETestID
from oeqa.utils.commands import runqemu

class DevtoolDeployTests(devtool.DevtoolCommon):
    @OETestID(1272)
    def test_devtool_deploy_target(self):
        # NOTE: Whilst this test would seemingly be better placed as a runtime test,
        # unfortunately the runtime tests run under bitbake and you can't run
        # devtool within bitbake (since devtool needs to run bitbake itself).
        # Additionally we are testing build-time functionality as well, so
        # really this has to be done as an oe-selftest test.
        #
        # Check preconditions
        machine = self.get_bb_var('MACHINE')
        if not machine.startswith('qemu'):
            self.skipTest('This test only works with qemu machines')
        if not os.path.exists('/etc/runqemu-nosudo'):
            self.skipTest('You must set up tap devices with scripts/runqemu-gen-tapdevs before running this test')
        result = self.runCmd('PATH="$PATH:/sbin:/usr/sbin" ip tuntap show', ignore_status=True)
        if result.status != 0:
            result = self.runCmd('PATH="$PATH:/sbin:/usr/sbin" ifconfig -a', ignore_status=True)
            if result.status != 0:
                self.skipTest('Failed to determine if tap devices exist with ifconfig or ip: %s' % result.output)
        for line in result.output.splitlines():
            if line.startswith('tap'):
                break
        else:
            self.skipTest('No tap devices found - you must set up tap devices with scripts/runqemu-gen-tapdevs before running this test')
        self.assertTrue(not os.path.exists(self.workspacedir), 'This test cannot be run with a workspace directory under the build directory')
        # Definitions
        testrecipe = 'mdadm'
        testfile = '/sbin/mdadm'
        testimage = 'oe-selftest-image'
        testcommand = '/sbin/mdadm --help'
        # Build an image to run
        self.bitbake("%s qemu-native qemu-helper-native" % testimage)
        deploy_dir_image = self.get_bb_var('DEPLOY_DIR_IMAGE')
        self.add_command_to_tearDown('bitbake -c clean %s' % testimage)
        self.add_command_to_tearDown('rm -f %s/%s*' % (deploy_dir_image, testimage))
        # Clean recipe so the first deploy will fail
        self.bitbake("%s -c clean" % testrecipe)
        # Try devtool modify
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        self.add_command_to_tearDown('bitbake -c clean %s' % testrecipe)
        result = self.runCmd('devtool modify %s -x %s' % (testrecipe, tempdir))
        # Test that deploy-target at this point fails (properly)
        result = self.runCmd('devtool deploy-target -n %s root@localhost' % testrecipe, ignore_status=True)
        self.assertNotEqual(result.output, 0, 'devtool deploy-target should have failed, output: %s' % result.output)
        self.assertNotIn(result.output, 'Traceback', 'devtool deploy-target should have failed with a proper error not a traceback, output: %s' % result.output)
        result = self.runCmd('devtool build %s' % testrecipe)
        # First try a dry-run of deploy-target
        result = self.runCmd('devtool deploy-target -n %s root@localhost' % testrecipe)
        self.assertIn('  %s' % testfile, result.output)
        # Boot the image
        with runqemu(testimage) as qemu:
            # Now really test deploy-target
            result = self.runCmd('devtool deploy-target -c %s root@%s' % (testrecipe, qemu.ip))
            # Run a test command to see if it was installed properly
            sshargs = '-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no'
            result = self.runCmd('ssh %s root@%s %s' % (sshargs, qemu.ip, testcommand))
            # Check if it deployed all of the files with the right ownership/perms
            # First look on the host - need to do this under pseudo to get the correct ownership/perms
            bb_vars = self.get_bb_vars(['D', 'FAKEROOTENV', 'FAKEROOTCMD'], testrecipe)
            installdir = bb_vars['D']
            fakerootenv = bb_vars['FAKEROOTENV']
            fakerootcmd = bb_vars['FAKEROOTCMD']
            result = self.runCmd('%s %s find . -type f -exec ls -l {} \;' % (fakerootenv, fakerootcmd), cwd=installdir)
            filelist1 = self._process_ls_output(result.output)

            # Now look on the target
            tempdir2 = tempfile.mkdtemp(prefix='devtoolqa')
            self.track_for_cleanup(tempdir2)
            tmpfilelist = os.path.join(tempdir2, 'files.txt')
            with open(tmpfilelist, 'w') as f:
                for line in filelist1:
                    splitline = line.split()
                    f.write(splitline[-1] + '\n')
            result = self.runCmd('cat %s | ssh -q %s root@%s \'xargs ls -l\'' % (tmpfilelist, sshargs, qemu.ip))
            filelist2 = self._process_ls_output(result.output)
            filelist1.sort(key=lambda item: item.split()[-1])
            filelist2.sort(key=lambda item: item.split()[-1])
            self.assertEqual(filelist1, filelist2)
            # Test undeploy-target
            result = self.runCmd('devtool undeploy-target -c %s root@%s' % (testrecipe, qemu.ip))
            result = self.runCmd('ssh %s root@%s %s' % (sshargs, qemu.ip, testcommand), ignore_status=True)
            self.assertNotEqual(result, 0, 'undeploy-target did not remove command as it should have')
