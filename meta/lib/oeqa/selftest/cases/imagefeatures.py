import os

from oeqa.selftest.case import OESelftestTestCase
from oeqa.core.decorator.oeid import OETestID

class ImageFeatures(OESelftestTestCase):
    _use_own_builddir = True
    _main_thread = False

    @OETestID(1116)
    def test_clutter_image_can_be_built(self):
        """
        Summary:     Check if clutter image can be built
        Expected:    1. core-image-clutter can be built
        Product:     oe-core
        Author:      Ionut Chisanovici <ionutx.chisanovici@intel.com>
        AutomatedBy: Daniel Istrate <daniel.alexandrux.istrate@intel.com>
        """

        # Build a core-image-clutter
        self.bitbake('core-image-clutter')

    @OETestID(1117)
    def test_wayland_support_in_image(self):
        """
        Summary:     Check Wayland support in image
        Expected:    1. Wayland image can be build
                     2. Wayland feature can be installed
        Product:     oe-core
        Author:      Ionut Chisanovici <ionutx.chisanovici@intel.com>
        AutomatedBy: Daniel Istrate <daniel.alexandrux.istrate@intel.com>
        """

        distro_features = self.get_bb_var('DISTRO_FEATURES')
        if not ('opengl' in distro_features and 'wayland' in distro_features):
            self.skipTest('neither opengl nor wayland present on DISTRO_FEATURES so core-image-weston cannot be built')

        # Build a core-image-weston
        self.bitbake('core-image-weston')

    @OETestID(1497)
    def test_bmap(self):
        """
        Summary:     Check bmap support
        Expected:    1. core-image-minimal can be build with bmap support
                     2. core-image-minimal is sparse
        Product:     oe-core
        Author:      Ed Bartosh <ed.bartosh@linux.intel.com>
        """

        features = 'IMAGE_FSTYPES += " ext4 ext4.bmap"'
        self.write_config(features)

        image_name = 'core-image-minimal'
        self.bitbake(image_name)

        deploy_dir_image = self.get_bb_var('DEPLOY_DIR_IMAGE')
        link_name = self.get_bb_var('IMAGE_LINK_NAME', image_name)
        image_path = os.path.join(deploy_dir_image, "%s.ext4" % link_name)
        bmap_path = "%s.bmap" % image_path

        # check if result image and bmap file are in deploy directory
        self.assertTrue(os.path.exists(image_path))
        self.assertTrue(os.path.exists(bmap_path))

        # check if result image is sparse
        image_stat = os.stat(image_path)
        self.assertTrue(image_stat.st_size > image_stat.st_blocks * 512)

    def test_image_fstypes(self):
        """
        Summary:     Check if image of supported image fstypes can be built
        Expected:    core-image-minimal can be built for various image types
        Product:     oe-core
        Author:      Ed Bartosh <ed.bartosh@linux.intel.com>
        """
        image_name = 'core-image-minimal'

        img_types = [itype for itype in self.get_bb_var("IMAGE_TYPES", image_name).split() \
                         if itype not in ('container', 'elf', 'multiubi')]

        config = 'IMAGE_FSTYPES += "%s"\n'\
                 'MKUBIFS_ARGS ?= "-m 2048 -e 129024 -c 2047"\n'\
                 'UBINIZE_ARGS ?= "-m 2048 -p 128KiB -s 512"' % ' '.join(img_types)

        self.write_config(config)

        self.bitbake(image_name)

        deploy_dir_image = self.get_bb_var('DEPLOY_DIR_IMAGE')
        link_name = self.get_bb_var('IMAGE_LINK_NAME', image_name)
        for itype in img_types:
            image_path = os.path.join(deploy_dir_image, "%s.%s" % (link_name, itype))
            # check if result image is in deploy directory
            self.assertTrue(os.path.exists(image_path),
                            "%s image %s doesn't exist" % (itype, image_path))
