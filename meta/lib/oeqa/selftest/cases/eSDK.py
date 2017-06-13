import tempfile
import shutil
import os
import glob
from oeqa.core.decorator.oeid import OETestID
from oeqa.selftest.case import OESelftestTestCase

class oeSDKExtSelfTest(OESelftestTestCase):
    _use_own_builddir = True
    _main_thread = False

    """
    # Bugzilla Test Plan: 6033
    # This code is planned to be part of the automation for eSDK containig
    # Install libraries and headers, image generation binary feeds, sdk-update.
    """
    @classmethod
    def get_esdk_environment(cls, env_eSDK, tmpdir_eSDKQA):
        # XXX: at this time use the first env need to investigate
        # what environment load oe-selftest, i586, x86_64
        pattern = os.path.join(tmpdir_eSDKQA, 'environment-setup-*')
        return glob.glob(pattern)[0]

    @classmethod
    def run_esdk_cmd(cls, env_eSDK, tmpdir_eSDKQA, cmd, postconfig=None, **options):
        if postconfig:
            esdk_conf_file = os.path.join(tmpdir_eSDKQA, 'conf', 'local.conf')
            with open(esdk_conf_file, 'a+') as f:
                f.write(postconfig)
        if not options:
            options = {}
        if not 'shell' in options:
            options['shell'] = True

        cls.runCmd("cd %s; . %s; %s" % (tmpdir_eSDKQA, env_eSDK, cmd), **options)

    @classmethod
    def generate_eSDK(cls, image):
        pn_task = '%s -c populate_sdk_ext' % image
        cls.bitbake(pn_task)

    @classmethod
    def get_eSDK_toolchain(cls, image):
        pn_task = '%s -c populate_sdk_ext' % image

        bb_vars = cls.get_bb_vars(['SDK_DEPLOY', 'TOOLCHAINEXT_OUTPUTNAME'], pn_task)
        sdk_deploy = bb_vars['SDK_DEPLOY']
        toolchain_name = bb_vars['TOOLCHAINEXT_OUTPUTNAME']
        return os.path.join(sdk_deploy, toolchain_name + '.sh')

    @classmethod
    def setUpClass(cls):
        super(oeSDKExtSelfTest, cls).setUpClass()
        cls.tmpdir_eSDKQA = tempfile.mkdtemp(prefix='eSDKQA')

        sstate_dir = cls.get_bb_var('SSTATE_DIR')

        cls.image = 'core-image-minimal'
        cls.generate_eSDK(cls.image)

        # Install eSDK
        cls.ext_sdk_path = cls.get_eSDK_toolchain(cls.image)
        cls.runCmd("%s -y -d \"%s\"" % (cls.ext_sdk_path, cls.tmpdir_eSDKQA))

        cls.env_eSDK = cls.get_esdk_environment('', cls.tmpdir_eSDKQA)

        # Configure eSDK to use sstate mirror from poky
        sstate_config="""
SDK_LOCAL_CONF_WHITELIST = "SSTATE_MIRRORS"
SSTATE_MIRRORS =  "file://.* file://%s/PATH"
            """ % sstate_dir
        with open(os.path.join(cls.tmpdir_eSDKQA, 'conf', 'local.conf'), 'a+') as f:
            f.write(sstate_config)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir_eSDKQA, ignore_errors=True)
        super(oeSDKExtSelfTest, cls).tearDownClass()

    @OETestID(1602)
    def test_install_libraries_headers(self):
        pn_sstate = 'bc'
        self.bitbake(pn_sstate)
        cmd = "devtool sdk-install %s " % pn_sstate
        self.run_esdk_cmd(self.env_eSDK, self.tmpdir_eSDKQA, cmd)

    @OETestID(1603)
    def test_image_generation_binary_feeds(self):
        image = 'core-image-minimal'
        cmd = "devtool build-image %s" % image
        self.run_esdk_cmd(self.env_eSDK, self.tmpdir_eSDKQA, cmd)
