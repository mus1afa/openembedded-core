import os
import re
import shutil
import tempfile
import glob
import fnmatch

import oeqa.utils.ftools as ftools
from oeqa.utils.commands import create_temp_layer

from oeqa.selftest.case import OESelftestTestCase
from oeqa.core.decorator.oeid import OETestID

class DevtoolBase(OESelftestTestCase):
    def _test_recipe_contents(self, recipefile, checkvars, checkinherits):
        with open(recipefile, 'r') as f:
            invar = None
            invalue = None
            for line in f:
                var = None
                if invar:
                    value = line.strip().strip('"')
                    if value.endswith('\\'):
                        invalue += ' ' + value[:-1].strip()
                        continue
                    else:
                        invalue += ' ' + value.strip()
                        var = invar
                        value = invalue
                        invar = None
                elif '=' in line:
                    splitline = line.split('=', 1)
                    var = splitline[0].rstrip()
                    value = splitline[1].strip().strip('"')
                    if value.endswith('\\'):
                        invalue = value[:-1].strip()
                        invar = var
                        continue
                elif line.startswith('inherit '):
                    inherits = line.split()[1:]

                if var and var in checkvars:
                    needvalue = checkvars.pop(var)
                    if needvalue is None:
                        self.fail('Variable %s should not appear in recipe, but value is being set to "%s"' % (var, value))
                    if isinstance(needvalue, set):
                        if var == 'LICENSE':
                            value = set(value.split(' & '))
                        else:
                            value = set(value.split())
                    self.assertEqual(value, needvalue, 'values for %s do not match' % var)


        missingvars = {}
        for var, value in checkvars.items():
            if value is not None:
                missingvars[var] = value
        self.assertEqual(missingvars, {}, 'Some expected variables not found in recipe: %s' % checkvars)

        for inherit in checkinherits:
            self.assertIn(inherit, inherits, 'Missing inherit of %s' % inherit)

    def _check_bbappend(self, testrecipe, recipefile, appenddir):
        result = self.runCmd('bitbake-layers show-appends', cwd=self.builddir)
        resultlines = result.output.splitlines()
        inrecipe = False
        bbappends = []
        bbappendfile = None
        for line in resultlines:
            if inrecipe:
                if line.startswith(' '):
                    bbappends.append(line.strip())
                else:
                    break
            elif line == '%s:' % os.path.basename(recipefile):
                inrecipe = True
        self.assertLessEqual(len(bbappends), 2, '%s recipe is being bbappended by another layer - bbappends found:\n  %s' % (testrecipe, '\n  '.join(bbappends)))
        for bbappend in bbappends:
            if bbappend.startswith(appenddir):
                bbappendfile = bbappend
                break
        else:
            self.fail('bbappend for recipe %s does not seem to be created in test layer' % testrecipe)
        return bbappendfile

    def _create_temp_layer(self, templayerdir, addlayer, templayername, priority=999, recipepathspec='recipes-*/*'):
        create_temp_layer(templayerdir, templayername, priority, recipepathspec)
        if addlayer:
            self.add_command_to_tearDown('bitbake-layers remove-layer %s || true' % templayerdir)
            result = self.runCmd('bitbake-layers add-layer %s' % templayerdir, cwd=self.builddir)

    def _process_ls_output(self, output):
        """
        Convert ls -l output to a format we can reasonably compare from one context
        to another (e.g. from host to target)
        """
        filelist = []
        for line in output.splitlines():
            splitline = line.split()
            if len(splitline) < 8:
                self.fail('_process_ls_output: invalid output line: %s' % line)
            # Remove trailing . on perms
            splitline[0] = splitline[0].rstrip('.')
            # Remove leading . on paths
            splitline[-1] = splitline[-1].lstrip('.')
            # Drop fields we don't want to compare
            del splitline[7]
            del splitline[6]
            del splitline[5]
            del splitline[4]
            del splitline[1]
            filelist.append(' '.join(splitline))
        return filelist

    def _check_src_repo(self, repo_dir):
        """Check srctree git repository"""
        self.assertTrue(os.path.isdir(os.path.join(repo_dir, '.git')),
                        'git repository for external source tree not found')
        result = self.runCmd('git status --porcelain', cwd=repo_dir)
        self.assertEqual(result.output.strip(), "",
                         'Created git repo is not clean')
        result = self.runCmd('git symbolic-ref HEAD', cwd=repo_dir)
        self.assertEqual(result.output.strip(), "refs/heads/devtool",
                         'Wrong branch in git repo')

    def _check_repo_status(self, repo_dir, expected_status):
        """Check the worktree status of a repository"""
        result = self.runCmd('git status . --porcelain',
                        cwd=repo_dir)
        for line in result.output.splitlines():
            for ind, (f_status, fn_re) in enumerate(expected_status):
                if re.match(fn_re, line[3:]):
                    if f_status != line[:2]:
                        self.fail('Unexpected status in line: %s' % line)
                    expected_status.pop(ind)
                    break
            else:
                self.fail('Unexpected modified file in line: %s' % line)
        if expected_status:
            self.fail('Missing file changes: %s' % expected_status)

class DevtoolCommon(DevtoolBase):
    _use_own_builddir = True
    _main_thread = False

    @classmethod
    def setUpClass(cls):
        super(DevtoolCommon, cls).setUpClass()
        bb_vars = cls.get_bb_vars(['TOPDIR', 'SSTATE_DIR'])
        cls.original_sstate = bb_vars['SSTATE_DIR']
        cls.devtool_sstate = os.path.join(bb_vars['TOPDIR'], 'sstate_devtool')
        cls.sstate_conf  = 'SSTATE_DIR = "%s"\n' % cls.devtool_sstate
        cls.sstate_conf += ('SSTATE_MIRRORS += "file://.* file:///%s/PATH"\n'
                            % cls.original_sstate)

        # XXX: some test cases needs xz-native to unpack like mdadm recipes
        # and it is supposed to be provided
        cls.bitbake("xz-native")

    @classmethod
    def tearDownClass(cls):
        cls.logger.debug('Deleting devtool sstate cache on %s' % cls.devtool_sstate)
        cls.runCmd('rm -rf %s' % cls.devtool_sstate)
        super(DevtoolCommon, cls).tearDownClass()

    def setUp(self):
        """Test case setup function"""
        super(DevtoolCommon, self).setUp()
        self.workspacedir = os.path.join(self.builddir, 'workspace')
        self.assertTrue(not os.path.exists(self.workspacedir),
                        'This test cannot be run with a workspace directory '
                        'under the build directory')
        self.append_config(self.sstate_conf)

class DevtoolTests(DevtoolCommon):
    _use_own_builddir = True
    _main_thread = False

    @OETestID(1158)
    def test_create_workspace(self):
        # Check preconditions
        result = self.runCmd('bitbake-layers show-layers')
        self.assertTrue('/workspace' not in result.output, 'This test cannot be run with a workspace layer in bblayers.conf')
        # Try creating a workspace layer with a specific path
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        result = self.runCmd('devtool create-workspace %s' % tempdir)
        self.assertTrue(os.path.isfile(os.path.join(tempdir, 'conf', 'layer.conf')), msg = "No workspace created. devtool output: %s " % result.output)
        result = self.runCmd('bitbake-layers show-layers')
        self.assertIn(tempdir, result.output)
        # Try creating a workspace layer with the default path
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        result = self.runCmd('devtool create-workspace')
        self.assertTrue(os.path.isfile(os.path.join(self.workspacedir, 'conf', 'layer.conf')), msg = "No workspace created. devtool output: %s " % result.output)
        result = self.runCmd('bitbake-layers show-layers')
        self.assertNotIn(tempdir, result.output)
        self.assertIn(self.workspacedir, result.output)

    @OETestID(1159)
    def test_devtool_add(self):
        # Fetch source
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        url = 'http://www.ivarch.com/programs/sources/pv-1.5.3.tar.bz2'
        result = self.runCmd('wget %s' % url, cwd=tempdir)
        result = self.runCmd('tar xfv pv-1.5.3.tar.bz2', cwd=tempdir)
        srcdir = os.path.join(tempdir, 'pv-1.5.3')
        self.assertTrue(os.path.isfile(os.path.join(srcdir, 'configure')), 'Unable to find configure script in source directory')
        # Test devtool add
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake -c cleansstate pv')
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        result = self.runCmd('devtool add pv %s' % srcdir)
        self.assertExists(os.path.join(self.workspacedir, 'conf', 'layer.conf'), 'Workspace directory not created')
        # Test devtool status
        result = self.runCmd('devtool status')
        self.assertIn('pv', result.output)
        self.assertIn(srcdir, result.output)
        # Clean up anything in the workdir/sysroot/sstate cache (have to do this *after* devtool add since the recipe only exists then)
        self.bitbake('pv -c cleansstate')
        # Test devtool build
        result = self.runCmd('devtool build pv')
        bb_vars = self.get_bb_vars(['D', 'bindir'], 'pv')
        installdir = bb_vars['D']
        self.assertTrue(installdir, 'Could not query installdir variable')
        bindir = bb_vars['bindir']
        self.assertTrue(bindir, 'Could not query bindir variable')
        if bindir[0] == '/':
            bindir = bindir[1:]
        self.assertTrue(os.path.isfile(os.path.join(installdir, bindir, 'pv')), 'pv binary not found in D')

    @OETestID(1423)
    def test_devtool_add_git_local(self):
        # Fetch source from a remote URL, but do it outside of devtool
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        pn = 'dbus-wait'
        srcrev = '6cc6077a36fe2648a5f993fe7c16c9632f946517'
        # We choose an https:// git URL here to check rewriting the URL works
        url = 'https://git.yoctoproject.org/git/dbus-wait'
        # Force fetching to "noname" subdir so we verify we're picking up the name from autoconf
        # instead of the directory name
        result = self.runCmd('git clone %s noname' % url, cwd=tempdir)
        srcdir = os.path.join(tempdir, 'noname')
        result = self.runCmd('git reset --hard %s' % srcrev, cwd=srcdir)
        self.assertTrue(os.path.isfile(os.path.join(srcdir, 'configure.ac')), 'Unable to find configure script in source directory')
        # Test devtool add
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        # Don't specify a name since we should be able to auto-detect it
        result = self.runCmd('devtool add %s' % srcdir)
        self.assertExists(os.path.join(self.workspacedir, 'conf', 'layer.conf'), 'Workspace directory not created')
        # Check the recipe name is correct
        recipefile = self.get_bb_var('FILE', pn)
        self.assertIn('%s_git.bb' % pn, recipefile, 'Recipe file incorrectly named')
        self.assertIn(recipefile, result.output)
        # Test devtool status
        result = self.runCmd('devtool status')
        self.assertIn(pn, result.output)
        self.assertIn(srcdir, result.output)
        self.assertIn(recipefile, result.output)
        checkvars = {}
        checkvars['LICENSE'] = 'GPLv2'
        checkvars['LIC_FILES_CHKSUM'] = 'file://COPYING;md5=b234ee4d69f5fce4486a80fdaf4a4263'
        checkvars['S'] = '${WORKDIR}/git'
        checkvars['PV'] = '0.1+git${SRCPV}'
        checkvars['SRC_URI'] = 'git://git.yoctoproject.org/git/dbus-wait;protocol=https'
        checkvars['SRCREV'] = srcrev
        checkvars['DEPENDS'] = set(['dbus'])
        self._test_recipe_contents(recipefile, checkvars, [])

    @OETestID(1162)
    def test_devtool_add_library(self):
        # Fetch source
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        version = '1.1'
        url = 'https://www.intra2net.com/en/developer/libftdi/download/libftdi1-%s.tar.bz2' % version
        result = self.runCmd('wget %s' % url, cwd=tempdir)
        result = self.runCmd('tar xfv libftdi1-%s.tar.bz2' % version, cwd=tempdir)
        srcdir = os.path.join(tempdir, 'libftdi1-%s' % version)
        self.assertTrue(os.path.isfile(os.path.join(srcdir, 'CMakeLists.txt')), 'Unable to find CMakeLists.txt in source directory')
        # Test devtool add (and use -V so we test that too)
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        result = self.runCmd('devtool add libftdi %s -V %s' % (srcdir, version))
        self.assertExists(os.path.join(self.workspacedir, 'conf', 'layer.conf'), 'Workspace directory not created')
        # Test devtool status
        result = self.runCmd('devtool status')
        self.assertIn('libftdi', result.output)
        self.assertIn(srcdir, result.output)
        # Clean up anything in the workdir/sysroot/sstate cache (have to do this *after* devtool add since the recipe only exists then)
        self.bitbake('libftdi -c cleansstate')
        # libftdi's python/CMakeLists.txt is a bit broken, so let's just disable it
        # There's also the matter of it installing cmake files to a path we don't
        # normally cover, which triggers the installed-vs-shipped QA test we have
        # within do_package
        recipefile = '%s/recipes/libftdi/libftdi_%s.bb' % (self.workspacedir, version)
        result = self.runCmd('recipetool setvar %s EXTRA_OECMAKE -- \'-DPYTHON_BINDINGS=OFF -DLIBFTDI_CMAKE_CONFIG_DIR=${datadir}/cmake/Modules\'' % recipefile)
        with open(recipefile, 'a') as f:
            f.write('\nFILES_${PN}-dev += "${datadir}/cmake/Modules"\n')
            # We don't have the ability to pick up this dependency automatically yet...
            f.write('\nDEPENDS += "libusb1"\n')
            f.write('\nTESTLIBOUTPUT = "${COMPONENTS_DIR}/${TUNE_PKGARCH}/${PN}/${libdir}"\n')
        # Test devtool build
        result = self.runCmd('devtool build libftdi')
        bb_vars = self.get_bb_vars(['TESTLIBOUTPUT', 'STAMP'], 'libftdi')
        staging_libdir = bb_vars['TESTLIBOUTPUT']
        self.assertTrue(staging_libdir, 'Could not query TESTLIBOUTPUT variable')
        self.assertTrue(os.path.isfile(os.path.join(staging_libdir, 'libftdi1.so.2.1.0')), "libftdi binary not found in STAGING_LIBDIR. Output of devtool build libftdi %s" % result.output)
        # Test devtool reset
        stampprefix = bb_vars['STAMP']
        result = self.runCmd('devtool reset libftdi')
        result = self.runCmd('devtool status')
        self.assertNotIn('libftdi', result.output)
        self.assertTrue(stampprefix, 'Unable to get STAMP value for recipe libftdi')
        matches = glob.glob(stampprefix + '*')
        self.assertFalse(matches, 'Stamp files exist for recipe libftdi that should have been cleaned')
        self.assertFalse(os.path.isfile(os.path.join(staging_libdir, 'libftdi1.so.2.1.0')), 'libftdi binary still found in STAGING_LIBDIR after cleaning')

    @OETestID(1160)
    def test_devtool_add_fetch(self):
        # Fetch source
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        testver = '0.23'
        url = 'https://pypi.python.org/packages/source/M/MarkupSafe/MarkupSafe-%s.tar.gz' % testver
        testrecipe = 'python-markupsafe'
        srcdir = os.path.join(tempdir, testrecipe)
        # Test devtool add
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake -c cleansstate %s' % testrecipe)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        result = self.runCmd('devtool add %s %s -f %s' % (testrecipe, srcdir, url))
        self.assertExists(os.path.join(self.workspacedir, 'conf', 'layer.conf'), 'Workspace directory not created. %s' % result.output)
        self.assertTrue(os.path.isfile(os.path.join(srcdir, 'setup.py')), 'Unable to find setup.py in source directory')
        self.assertTrue(os.path.isdir(os.path.join(srcdir, '.git')), 'git repository for external source tree was not created')
        # Test devtool status
        result = self.runCmd('devtool status')
        self.assertIn(testrecipe, result.output)
        self.assertIn(srcdir, result.output)
        # Check recipe
        recipefile = self.get_bb_var('FILE', testrecipe)
        self.assertIn('%s_%s.bb' % (testrecipe, testver), recipefile, 'Recipe file incorrectly named')
        checkvars = {}
        checkvars['S'] = '${WORKDIR}/MarkupSafe-${PV}'
        checkvars['SRC_URI'] = url.replace(testver, '${PV}')
        self._test_recipe_contents(recipefile, checkvars, [])
        # Try with version specified
        result = self.runCmd('devtool reset -n %s' % testrecipe)
        shutil.rmtree(srcdir)
        fakever = '1.9'
        result = self.runCmd('devtool add %s %s -f %s -V %s' % (testrecipe, srcdir, url, fakever))
        self.assertTrue(os.path.isfile(os.path.join(srcdir, 'setup.py')), 'Unable to find setup.py in source directory')
        # Test devtool status
        result = self.runCmd('devtool status')
        self.assertIn(testrecipe, result.output)
        self.assertIn(srcdir, result.output)
        # Check recipe
        recipefile = self.get_bb_var('FILE', testrecipe)
        self.assertIn('%s_%s.bb' % (testrecipe, fakever), recipefile, 'Recipe file incorrectly named')
        checkvars = {}
        checkvars['S'] = '${WORKDIR}/MarkupSafe-%s' % testver
        checkvars['SRC_URI'] = url
        self._test_recipe_contents(recipefile, checkvars, [])

    @OETestID(1161)
    def test_devtool_add_fetch_git(self):
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        url = 'gitsm://git.yoctoproject.org/mraa'
        checkrev = 'ae127b19a50aa54255e4330ccfdd9a5d058e581d'
        testrecipe = 'mraa'
        srcdir = os.path.join(tempdir, testrecipe)
        # Test devtool add
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake -c cleansstate %s' % testrecipe)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        result = self.runCmd('devtool add %s %s -a -f %s' % (testrecipe, srcdir, url))
        self.assertExists(os.path.join(self.workspacedir, 'conf', 'layer.conf'), 'Workspace directory not created: %s' % result.output)
        self.assertTrue(os.path.isfile(os.path.join(srcdir, 'imraa', 'imraa.c')), 'Unable to find imraa/imraa.c in source directory')
        # Test devtool status
        result = self.runCmd('devtool status')
        self.assertIn(testrecipe, result.output)
        self.assertIn(srcdir, result.output)
        # Check recipe
        recipefile = self.get_bb_var('FILE', testrecipe)
        self.assertIn('_git.bb', recipefile, 'Recipe file incorrectly named')
        checkvars = {}
        checkvars['S'] = '${WORKDIR}/git'
        checkvars['PV'] = '1.0+git${SRCPV}'
        checkvars['SRC_URI'] = url
        checkvars['SRCREV'] = '${AUTOREV}'
        self._test_recipe_contents(recipefile, checkvars, [])
        # Try with revision and version specified
        result = self.runCmd('devtool reset -n %s' % testrecipe)
        shutil.rmtree(srcdir)
        url_rev = '%s;rev=%s' % (url, checkrev)
        result = self.runCmd('devtool add %s %s -f "%s" -V 1.5' % (testrecipe, srcdir, url_rev))
        self.assertTrue(os.path.isfile(os.path.join(srcdir, 'imraa', 'imraa.c')), 'Unable to find imraa/imraa.c in source directory')
        # Test devtool status
        result = self.runCmd('devtool status')
        self.assertIn(testrecipe, result.output)
        self.assertIn(srcdir, result.output)
        # Check recipe
        recipefile = self.get_bb_var('FILE', testrecipe)
        self.assertIn('_git.bb', recipefile, 'Recipe file incorrectly named')
        checkvars = {}
        checkvars['S'] = '${WORKDIR}/git'
        checkvars['PV'] = '1.5+git${SRCPV}'
        checkvars['SRC_URI'] = url
        checkvars['SRCREV'] = checkrev
        self._test_recipe_contents(recipefile, checkvars, [])

    @OETestID(1391)
    def test_devtool_add_fetch_simple(self):
        # Fetch source from a remote URL, auto-detecting name
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        testver = '1.6.0'
        url = 'http://www.ivarch.com/programs/sources/pv-%s.tar.bz2' % testver
        testrecipe = 'pv'
        srcdir = os.path.join(self.workspacedir, 'sources', testrecipe)
        # Test devtool add
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        result = self.runCmd('devtool add %s' % url)
        self.assertExists(os.path.join(self.workspacedir, 'conf', 'layer.conf'), 'Workspace directory not created. %s' % result.output)
        self.assertTrue(os.path.isfile(os.path.join(srcdir, 'configure')), 'Unable to find configure script in source directory')
        self.assertTrue(os.path.isdir(os.path.join(srcdir, '.git')), 'git repository for external source tree was not created')
        # Test devtool status
        result = self.runCmd('devtool status')
        self.assertIn(testrecipe, result.output)
        self.assertIn(srcdir, result.output)
        # Check recipe
        recipefile = self.get_bb_var('FILE', testrecipe)
        self.assertIn('%s_%s.bb' % (testrecipe, testver), recipefile, 'Recipe file incorrectly named')
        checkvars = {}
        checkvars['S'] = None
        checkvars['SRC_URI'] = url.replace(testver, '${PV}')
        self._test_recipe_contents(recipefile, checkvars, [])

    @OETestID(1164)
    def test_devtool_modify(self):
        import oe.path

        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        self.add_command_to_tearDown('bitbake -c clean mdadm')
        result = self.runCmd('devtool modify mdadm -x %s' % tempdir)
        self.assertExists(os.path.join(tempdir, 'Makefile'), 'Extracted source could not be found')
        self.assertExists(os.path.join(self.workspacedir, 'conf', 'layer.conf'), 'Workspace directory not created')
        matches = glob.glob(os.path.join(self.workspacedir, 'appends', 'mdadm_*.bbappend'))
        self.assertTrue(matches, 'bbappend not created %s' % result.output)

        # Test devtool status
        result = self.runCmd('devtool status')
        self.assertIn('mdadm', result.output)
        self.assertIn(tempdir, result.output)
        self._check_src_repo(tempdir)

        self.bitbake('mdadm -C unpack')

        def check_line(checkfile, expected, message, present=True):
            # Check for $expected, on a line on its own, in checkfile.
            with open(checkfile, 'r') as f:
                if present:
                    self.assertIn(expected + '\n', f, message)
                else:
                    self.assertNotIn(expected + '\n', f, message)

        modfile = os.path.join(tempdir, 'mdadm.8.in')
        bb_vars = self.get_bb_vars(['PKGD', 'mandir'], 'mdadm')
        pkgd = bb_vars['PKGD']
        self.assertTrue(pkgd, 'Could not query PKGD variable')
        mandir = bb_vars['mandir']
        self.assertTrue(mandir, 'Could not query mandir variable')
        manfile = oe.path.join(pkgd, mandir, 'man8', 'mdadm.8')

        check_line(modfile, 'Linux Software RAID', 'Could not find initial string')
        check_line(modfile, 'antique pin sardine', 'Unexpectedly found replacement string', present=False)

        result = self.runCmd("sed -i 's!^Linux Software RAID$!antique pin sardine!' %s" % modfile)
        check_line(modfile, 'antique pin sardine', 'mdadm.8.in file not modified (sed failed)')

        self.bitbake('mdadm -c package')
        check_line(manfile, 'antique pin sardine', 'man file not modified. man searched file path: %s' % manfile)

        result = self.runCmd('git checkout -- %s' % modfile, cwd=tempdir)
        check_line(modfile, 'Linux Software RAID', 'man .in file not restored (git failed)')

        self.bitbake('mdadm -c package')
        check_line(manfile, 'Linux Software RAID', 'man file not updated. man searched file path: %s' % manfile)

        result = self.runCmd('devtool reset mdadm')
        result = self.runCmd('devtool status')
        self.assertNotIn('mdadm', result.output)

    @OETestID(1620)
    def test_devtool_buildclean(self):
        def assertFile(path, *paths):
            f = os.path.join(path, *paths)
            self.assertExists(f)
        def assertNoFile(path, *paths):
            f = os.path.join(path, *paths)
            self.assertNotExists(f)

        # Clean up anything in the workdir/sysroot/sstate cache
        self.bitbake('mdadm m4 -c cleansstate')
        # Try modifying a recipe
        tempdir_mdadm = tempfile.mkdtemp(prefix='devtoolqa')
        tempdir_m4 = tempfile.mkdtemp(prefix='devtoolqa')
        builddir_m4 = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir_mdadm)
        self.track_for_cleanup(tempdir_m4)
        self.track_for_cleanup(builddir_m4)
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        self.add_command_to_tearDown('bitbake -c clean mdadm m4')
        self.write_recipeinc('m4', 'EXTERNALSRC_BUILD = "%s"\ndo_clean() {\n\t:\n}\n' % builddir_m4)
        try:
            self.runCmd('devtool modify mdadm -x %s' % tempdir_mdadm)
            self.runCmd('devtool modify m4 -x %s' % tempdir_m4)
            assertNoFile(tempdir_mdadm, 'mdadm')
            assertNoFile(builddir_m4, 'src/m4')
            result = self.bitbake('m4 -e')
            result = self.bitbake('mdadm m4 -c compile')
            self.assertEqual(result.status, 0)
            assertFile(tempdir_mdadm, 'mdadm')
            assertFile(builddir_m4, 'src/m4')
            # Check that buildclean task exists and does call make clean
            self.bitbake('mdadm m4 -c buildclean')
            assertNoFile(tempdir_mdadm, 'mdadm')
            assertNoFile(builddir_m4, 'src/m4')
            self.bitbake('mdadm m4 -c compile')
            assertFile(tempdir_mdadm, 'mdadm')
            assertFile(builddir_m4, 'src/m4')
            self.bitbake('mdadm m4 -c clean')
            # Check that buildclean task is run before clean for B == S
            assertNoFile(tempdir_mdadm, 'mdadm')
            # Check that buildclean task is not run before clean for B != S
            assertFile(builddir_m4, 'src/m4')
        finally:
            self.delete_recipeinc('m4')

    @OETestID(1166)
    def test_devtool_modify_invalid(self):
        # Try modifying some recipes
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)

        testrecipes = 'perf kernel-devsrc package-index core-image-minimal meta-toolchain packagegroup-core-sdk meta-ide-support'.split()
        # Find actual name of gcc-source since it now includes the version - crude, but good enough for this purpose
        result = self.runCmd('bitbake-layers show-recipes gcc-source*')
        for line in result.output.splitlines():
            # just match those lines that contain a real target
            m = re.match('(?P<recipe>^[a-zA-Z0-9.-]+)(?P<colon>:$)', line)
            if m:
                testrecipes.append(m.group('recipe'))
        for testrecipe in testrecipes:
            # Check it's a valid recipe
            self.bitbake('%s -e' % testrecipe)
            # devtool extract should fail
            result = self.runCmd('devtool extract %s %s' % (testrecipe, os.path.join(tempdir, testrecipe)), ignore_status=True)
            self.assertNotEqual(result.status, 0, 'devtool extract on %s should have failed. devtool output: %s' % (testrecipe, result.output))
            self.assertNotIn('Fetching ', result.output, 'devtool extract on %s should have errored out before trying to fetch' % testrecipe)
            self.assertIn('ERROR: ', result.output, 'devtool extract on %s should have given an ERROR' % testrecipe)
            # devtool modify should fail
            result = self.runCmd('devtool modify %s -x %s' % (testrecipe, os.path.join(tempdir, testrecipe)), ignore_status=True)
            self.assertNotEqual(result.status, 0, 'devtool modify on %s should have failed. devtool output: %s' %  (testrecipe, result.output))
            self.assertIn('ERROR: ', result.output, 'devtool modify on %s should have given an ERROR' % testrecipe)

    @OETestID(1365)
    def test_devtool_modify_native(self):
        # Check preconditions
        self.assertTrue(not os.path.exists(self.workspacedir), 'This test cannot be run with a workspace directory under the build directory')
        # Try modifying some recipes
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)

        bbclassextended = False
        inheritnative = False
        testrecipes = 'mtools-native apt-native desktop-file-utils-native'.split()
        for testrecipe in testrecipes:
            checkextend = 'native' in (self.get_bb_var('BBCLASSEXTEND', testrecipe) or '').split()
            if not bbclassextended:
                bbclassextended = checkextend
            if not inheritnative:
                inheritnative = not checkextend
            result = self.runCmd('devtool modify %s -x %s' % (testrecipe, os.path.join(tempdir, testrecipe)))
            self.assertNotIn('ERROR: ', result.output, 'ERROR in devtool modify output: %s' % result.output)
            result = self.runCmd('devtool build %s' % testrecipe)
            self.assertNotIn('ERROR: ', result.output, 'ERROR in devtool build output: %s' % result.output)
            result = self.runCmd('devtool reset %s' % testrecipe)
            self.assertNotIn('ERROR: ', result.output, 'ERROR in devtool reset output: %s' % result.output)

        self.assertTrue(bbclassextended, 'None of these recipes are BBCLASSEXTENDed to native - need to adjust testrecipes list: %s' % ', '.join(testrecipes))
        self.assertTrue(inheritnative, 'None of these recipes do "inherit native" - need to adjust testrecipes list: %s' % ', '.join(testrecipes))


    @OETestID(1165)
    def test_devtool_modify_git(self):
        # Check preconditions
        testrecipe = 'mkelfimage'
        src_uri = self.get_bb_var('SRC_URI', testrecipe)
        self.assertIn('git://', src_uri, 'This test expects the %s recipe to be a git recipe' % testrecipe)
        # Clean up anything in the workdir/sysroot/sstate cache
        self.bitbake('%s -c cleansstate' % testrecipe)
        # Try modifying a recipe
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        self.add_command_to_tearDown('bitbake -c clean %s' % testrecipe)
        result = self.runCmd('devtool modify %s -x %s' % (testrecipe, tempdir))
        self.assertExists(os.path.join(tempdir, 'Makefile'), 'Extracted source could not be found')
        self.assertExists(os.path.join(self.workspacedir, 'conf', 'layer.conf'), 'Workspace directory not created. devtool output: %s' % result.output)
        matches = glob.glob(os.path.join(self.workspacedir, 'appends', 'mkelfimage_*.bbappend'))
        self.assertTrue(matches, 'bbappend not created')
        # Test devtool status
        result = self.runCmd('devtool status')
        self.assertIn(testrecipe, result.output)
        self.assertIn(tempdir, result.output)
        # Check git repo
        self._check_src_repo(tempdir)
        # Try building
        self.bitbake(testrecipe)

    @OETestID(1167)
    def test_devtool_modify_localfiles(self):
        # Check preconditions
        testrecipe = 'lighttpd'
        src_uri = (self.get_bb_var('SRC_URI', testrecipe) or '').split()
        foundlocal = False
        for item in src_uri:
            if item.startswith('file://') and '.patch' not in item:
                foundlocal = True
                break
        self.assertTrue(foundlocal, 'This test expects the %s recipe to fetch local files and it seems that it no longer does' % testrecipe)
        # Clean up anything in the workdir/sysroot/sstate cache
        self.bitbake('%s -c cleansstate' % testrecipe)
        # Try modifying a recipe
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        self.add_command_to_tearDown('bitbake -c clean %s' % testrecipe)
        result = self.runCmd('devtool modify %s -x %s' % (testrecipe, tempdir))
        self.assertExists(os.path.join(tempdir, 'configure.ac'), 'Extracted source could not be found')
        self.assertExists(os.path.join(self.workspacedir, 'conf', 'layer.conf'), 'Workspace directory not created')
        matches = glob.glob(os.path.join(self.workspacedir, 'appends', '%s_*.bbappend' % testrecipe))
        self.assertTrue(matches, 'bbappend not created')
        # Test devtool status
        result = self.runCmd('devtool status')
        self.assertIn(testrecipe, result.output)
        self.assertIn(tempdir, result.output)
        # Try building
        self.bitbake(testrecipe)

    @OETestID(1378)
    def test_devtool_modify_virtual(self):
        # Try modifying a virtual recipe
        virtrecipe = 'virtual/make'
        realrecipe = 'make'
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        result = self.runCmd('devtool modify %s -x %s' % (virtrecipe, tempdir))
        self.assertExists(os.path.join(tempdir, 'Makefile.am'), 'Extracted source could not be found')
        self.assertExists(os.path.join(self.workspacedir, 'conf', 'layer.conf'), 'Workspace directory not created')
        matches = glob.glob(os.path.join(self.workspacedir, 'appends', '%s_*.bbappend' % realrecipe))
        self.assertTrue(matches, 'bbappend not created %s' % result.output)
        # Test devtool status
        result = self.runCmd('devtool status')
        self.assertNotIn(virtrecipe, result.output)
        self.assertIn(realrecipe, result.output)
        # Check git repo
        self._check_src_repo(tempdir)
        # This is probably sufficient

    @OETestID(1163)
    def test_devtool_extract(self):
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        # Try devtool extract
        self.track_for_cleanup(tempdir)
        result = self.runCmd('devtool extract matchbox-terminal %s' % tempdir)
        self.assertExists(os.path.join(tempdir, 'Makefile.am'), 'Extracted source could not be found')
        # devtool extract shouldn't create the workspace
        self.assertNotExists(self.workspacedir)
        self._check_src_repo(tempdir)

    @OETestID(1379)
    def test_devtool_extract_virtual(self):
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        # Try devtool extract
        self.track_for_cleanup(tempdir)
        result = self.runCmd('devtool extract virtual/make %s' % tempdir)
        self.assertExists(os.path.join(tempdir, 'Makefile.am'), 'Extracted source could not be found')
        # devtool extract shouldn't create the workspace
        self.assertNotExists(self.workspacedir)
        self._check_src_repo(tempdir)

    @OETestID(1168)
    def test_devtool_reset_all(self):
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        testrecipe1 = 'mdadm'
        testrecipe2 = 'cronie'
        result = self.runCmd('devtool modify -x %s %s' % (testrecipe1, os.path.join(tempdir, testrecipe1)))
        result = self.runCmd('devtool modify -x %s %s' % (testrecipe2, os.path.join(tempdir, testrecipe2)))
        result = self.runCmd('devtool build %s' % testrecipe1)
        result = self.runCmd('devtool build %s' % testrecipe2)
        stampprefix1 = self.get_bb_var('STAMP', testrecipe1)
        self.assertTrue(stampprefix1, 'Unable to get STAMP value for recipe %s' % testrecipe1)
        stampprefix2 = self.get_bb_var('STAMP', testrecipe2)
        self.assertTrue(stampprefix2, 'Unable to get STAMP value for recipe %s' % testrecipe2)
        result = self.runCmd('devtool reset -a')
        self.assertIn(testrecipe1, result.output)
        self.assertIn(testrecipe2, result.output)
        result = self.runCmd('devtool status')
        self.assertNotIn(testrecipe1, result.output)
        self.assertNotIn(testrecipe2, result.output)
        matches1 = glob.glob(stampprefix1 + '*')
        self.assertFalse(matches1, 'Stamp files exist for recipe %s that should have been cleaned' % testrecipe1)
        matches2 = glob.glob(stampprefix2 + '*')
        self.assertFalse(matches2, 'Stamp files exist for recipe %s that should have been cleaned' % testrecipe2)

    @OETestID(1366)
    def test_devtool_build_image(self):
        """Test devtool build-image plugin"""
        # Check preconditions
        self.assertTrue(not os.path.exists(self.workspacedir), 'This test cannot be run with a workspace directory under the build directory')
        image = 'core-image-minimal'
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        self.add_command_to_tearDown('bitbake -c clean %s' % image)
        self.bitbake('%s -c clean' % image)
        # Add target and native recipes to workspace
        recipes = ['mdadm', 'parted-native']
        for recipe in recipes:
            tempdir = tempfile.mkdtemp(prefix='devtoolqa')
            self.track_for_cleanup(tempdir)
            self.add_command_to_tearDown('bitbake -c clean %s' % recipe)
            self.runCmd('devtool modify %s -x %s' % (recipe, tempdir))
        # Try to build image
        result = self.runCmd('devtool build-image %s' % image)
        self.assertNotEqual(result, 0, 'devtool build-image failed')
        # Check if image contains expected packages
        deploy_dir_image = self.get_bb_var('DEPLOY_DIR_IMAGE')
        image_link_name = self.get_bb_var('IMAGE_LINK_NAME', image)
        reqpkgs = [item for item in recipes if not item.endswith('-native')]
        with open(os.path.join(deploy_dir_image, image_link_name + '.manifest'), 'r') as f:
            for line in f:
                splitval = line.split()
                if splitval:
                    pkg = splitval[0]
                    if pkg in reqpkgs:
                        reqpkgs.remove(pkg)
        if reqpkgs:
            self.fail('The following packages were not present in the image as expected: %s' % ', '.join(reqpkgs))

    @OETestID(1367)
    def test_devtool_upgrade(self):
        # Check preconditions
        self.assertTrue(not os.path.exists(self.workspacedir), 'This test cannot be run with a workspace directory under the build directory')
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        # Check parameters
        result = self.runCmd('devtool upgrade -h')
        for param in 'recipename srctree --version -V --branch -b --keep-temp --no-patch'.split():
            self.assertIn(param, result.output)
        # For the moment, we are using a real recipe.
        recipe = 'devtool-upgrade-test1'
        version = '1.6.0'
        oldrecipefile = self.get_bb_var('FILE', recipe)
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        # Check that recipe is not already under devtool control
        result = self.runCmd('devtool status')
        self.assertNotIn(recipe, result.output)
        # Check upgrade. Code does not check if new PV is older or newer that current PV, so, it may be that
        # we are downgrading instead of upgrading.
        result = self.runCmd('devtool upgrade %s %s -V %s' % (recipe, tempdir, version))
        # Check if srctree at least is populated
        self.assertTrue(len(os.listdir(tempdir)) > 0, 'srctree (%s) should be populated with new (%s) source code' % (tempdir, version))
        # Check new recipe subdirectory is present
        self.assertExists(os.path.join(self.workspacedir, 'recipes', recipe, '%s-%s' % (recipe, version)), 'Recipe folder should exist')
        # Check new recipe file is present
        newrecipefile = os.path.join(self.workspacedir, 'recipes', recipe, '%s_%s.bb' % (recipe, version))
        self.assertExists(newrecipefile, 'Recipe file should exist after upgrade')
        # Check devtool status and make sure recipe is present
        result = self.runCmd('devtool status')
        self.assertIn(recipe, result.output)
        self.assertIn(tempdir, result.output)
        # Check recipe got changed as expected
        with open(oldrecipefile + '.upgraded', 'r') as f:
            desiredlines = f.readlines()
        with open(newrecipefile, 'r') as f:
            newlines = f.readlines()
        self.assertEqual(desiredlines, newlines)
        # Check devtool reset recipe
        result = self.runCmd('devtool reset %s -n' % recipe)
        result = self.runCmd('devtool status')
        self.assertNotIn(recipe, result.output)
        self.assertNotExists(os.path.join(self.workspacedir, 'recipes', recipe), 'Recipe directory should not exist after resetting')

    @OETestID(1433)
    def test_devtool_upgrade_git(self):
        # Check preconditions
        self.assertTrue(not os.path.exists(self.workspacedir), 'This test cannot be run with a workspace directory under the build directory')
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        recipe = 'devtool-upgrade-test2'
        commit = '6cc6077a36fe2648a5f993fe7c16c9632f946517'
        oldrecipefile = self.get_bb_var('FILE', recipe)
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        # Check that recipe is not already under devtool control
        result = self.runCmd('devtool status')
        self.assertNotIn(recipe, result.output)
        # Check upgrade
        result = self.runCmd('devtool upgrade %s %s -S %s' % (recipe, tempdir, commit))
        # Check if srctree at least is populated
        self.assertTrue(len(os.listdir(tempdir)) > 0, 'srctree (%s) should be populated with new (%s) source code' % (tempdir, commit))
        # Check new recipe file is present
        newrecipefile = os.path.join(self.workspacedir, 'recipes', recipe, os.path.basename(oldrecipefile))
        self.assertExists(newrecipefile, 'Recipe file should exist after upgrade')
        # Check devtool status and make sure recipe is present
        result = self.runCmd('devtool status')
        self.assertIn(recipe, result.output)
        self.assertIn(tempdir, result.output)
        # Check recipe got changed as expected
        with open(oldrecipefile + '.upgraded', 'r') as f:
            desiredlines = f.readlines()
        with open(newrecipefile, 'r') as f:
            newlines = f.readlines()
        self.assertEqual(desiredlines, newlines)
        # Check devtool reset recipe
        result = self.runCmd('devtool reset %s -n' % recipe)
        result = self.runCmd('devtool status')
        self.assertNotIn(recipe, result.output)
        self.assertNotExists(os.path.join(self.workspacedir, 'recipes', recipe), 'Recipe directory should not exist after resetting')

    @OETestID(1352)
    def test_devtool_layer_plugins(self):
        """Test that devtool can use plugins from other layers.

        This test executes the selftest-reverse command from meta-selftest."""

        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)

        s = "Microsoft Made No Profit From Anyone's Zunes Yo"
        result = self.runCmd("devtool --quiet selftest-reverse \"%s\"" % s)
        self.assertEqual(result.output, s[::-1])

    def _copy_file_with_cleanup(self, srcfile, basedstdir, *paths):
        dstdir = basedstdir
        self.assertExists(dstdir)
        for p in paths:
            dstdir = os.path.join(dstdir, p)
            if not os.path.exists(dstdir):
                os.makedirs(dstdir)
                self.track_for_cleanup(dstdir)
        dstfile = os.path.join(dstdir, os.path.basename(srcfile))
        if srcfile != dstfile:
            shutil.copy(srcfile, dstfile)
            self.track_for_cleanup(dstfile)

    @OETestID(1625)
    def test_devtool_load_plugin(self):
        """Test that devtool loads only the first found plugin in BBPATH."""

        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)

        devtool = self.runCmd("which devtool")
        fromname = self.runCmd("devtool --quiet pluginfile")
        srcfile = fromname.output
        bbpath = self.get_bb_var('BBPATH')
        searchpath = bbpath.split(':') + [os.path.dirname(devtool.output)]
        plugincontent = []
        with open(srcfile) as fh:
            plugincontent = fh.readlines()
        try:
            self.assertIn('meta-selftest', srcfile, 'wrong bbpath plugin found')
            for path in searchpath:
                self._copy_file_with_cleanup(srcfile, path, 'lib', 'devtool')
            result = self.runCmd("devtool --quiet count")
            self.assertEqual(result.output, '1')
            result = self.runCmd("devtool --quiet multiloaded")
            self.assertEqual(result.output, "no")
            for path in searchpath:
                result = self.runCmd("devtool --quiet bbdir")
                self.assertEqual(result.output, path)
                os.unlink(os.path.join(result.output, 'lib', 'devtool', 'bbpath.py'))
        finally:
            with open(srcfile, 'w') as fh:
                fh.writelines(plugincontent)

    @OETestID(1626)
    def test_devtool_rename(self):
        # Check preconditions
        self.assertTrue(not os.path.exists(self.workspacedir), 'This test cannot be run with a workspace directory under the build directory')
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)

        # First run devtool add
        # We already have this recipe in OE-Core, but that doesn't matter
        recipename = 'i2c-tools'
        recipever = '3.1.2'
        recipefile = os.path.join(self.workspacedir, 'recipes', recipename, '%s_%s.bb' % (recipename, recipever))
        url = 'http://downloads.yoctoproject.org/mirror/sources/i2c-tools-%s.tar.bz2' % recipever
        def add_recipe():
            result = self.runCmd('devtool add %s' % url)
            self.assertExists(recipefile, 'Expected recipe file not created')
            self.assertExists(os.path.join(self.workspacedir, 'sources', recipename), 'Source directory not created')
            checkvars = {}
            checkvars['S'] = None
            checkvars['SRC_URI'] = url.replace(recipever, '${PV}')
            self._test_recipe_contents(recipefile, checkvars, [])
        add_recipe()
        # Now rename it - change both name and version
        newrecipename = 'mynewrecipe'
        newrecipever = '456'
        newrecipefile = os.path.join(self.workspacedir, 'recipes', newrecipename, '%s_%s.bb' % (newrecipename, newrecipever))
        result = self.runCmd('devtool rename %s %s -V %s' % (recipename, newrecipename, newrecipever))
        self.assertExists(newrecipefile, 'Recipe file not renamed')
        self.assertNotExists(os.path.join(self.workspacedir, 'recipes', recipename), 'Old recipe directory still exists')
        newsrctree = os.path.join(self.workspacedir, 'sources', newrecipename)
        self.assertExists(newsrctree, 'Source directory not renamed')
        checkvars = {}
        checkvars['S'] = '${WORKDIR}/%s-%s' % (recipename, recipever)
        checkvars['SRC_URI'] = url
        self._test_recipe_contents(newrecipefile, checkvars, [])
        # Try again - change just name this time
        result = self.runCmd('devtool reset -n %s' % newrecipename)
        shutil.rmtree(newsrctree)
        add_recipe()
        newrecipefile = os.path.join(self.workspacedir, 'recipes', newrecipename, '%s_%s.bb' % (newrecipename, recipever))
        result = self.runCmd('devtool rename %s %s' % (recipename, newrecipename))
        self.assertExists(newrecipefile, 'Recipe file not renamed')
        self.assertNotExists(os.path.join(self.workspacedir, 'recipes', recipename), 'Old recipe directory still exists')
        self.assertExists(os.path.join(self.workspacedir, 'sources', newrecipename), 'Source directory not renamed')
        checkvars = {}
        checkvars['S'] = '${WORKDIR}/%s-${PV}' % recipename
        checkvars['SRC_URI'] = url.replace(recipever, '${PV}')
        self._test_recipe_contents(newrecipefile, checkvars, [])
        # Try again - change just version this time
        result = self.runCmd('devtool reset -n %s' % newrecipename)
        shutil.rmtree(newsrctree)
        add_recipe()
        newrecipefile = os.path.join(self.workspacedir, 'recipes', recipename, '%s_%s.bb' % (recipename, newrecipever))
        result = self.runCmd('devtool rename %s -V %s' % (recipename, newrecipever))
        self.assertExists(newrecipefile, 'Recipe file not renamed')
        self.assertExists(os.path.join(self.workspacedir, 'sources', recipename), 'Source directory no longer exists')
        checkvars = {}
        checkvars['S'] = '${WORKDIR}/${BPN}-%s' % recipever
        checkvars['SRC_URI'] = url
        self._test_recipe_contents(newrecipefile, checkvars, [])

    @OETestID(1577)
    def test_devtool_virtual_kernel_modify(self):
        """
        Summary:        The purpose of this test case is to verify that
                        devtool modify works correctly when building
                        the kernel.
        Dependencies:   NA
        Steps:          1. Build kernel with bitbake.
                        2. Save the config file generated.
                        3. Clean the environment.
                        4. Use `devtool modify virtual/kernel` to validate following:
                           4.1 The source is checked out correctly.
                           4.2 The resulting configuration is the same as
                               what was get on step 2.
                           4.3 The Kernel can be build correctly.
                           4.4 Changes made on the source are reflected on the
                               subsequent builds.
                           4.5 Changes on the configuration are reflected on the
                               subsequent builds
         Expected:       devtool modify is able to checkout the source of the kernel
                         and modification to the source and configurations are reflected
                         when building the kernel.
         """
        kernel_provider = self.get_bb_var('PREFERRED_PROVIDER_virtual/kernel')
        # Clean up the enviroment
        self.bitbake('%s -c clean' % kernel_provider)
        tempdir = tempfile.mkdtemp(prefix='devtoolqa')
        self.track_for_cleanup(tempdir)
        self.track_for_cleanup(self.workspacedir)
        self.add_command_to_tearDown('bitbake-layers remove-layer %s' % self.workspacedir)
        self.add_command_to_tearDown('bitbake -c clean %s' % kernel_provider)
        #Step 1
        #Here is just generated the config file instead of all the kernel to optimize the
        #time of executing this test case.
        self.bitbake('%s -c configure' % kernel_provider)
        bbconfig = os.path.join(self.get_bb_var('B', kernel_provider),'.config')
        buildir= self.get_bb_var('TOPDIR')
        #Step 2
        self.runCmd('cp %s %s' % (bbconfig, buildir))
        self.assertExists(os.path.join(buildir, '.config'), 'Could not copy .config file from kernel')

        tmpconfig = os.path.join(buildir, '.config')
        #Step 3
        self.bitbake('%s -c clean' % kernel_provider)
        #Step 4.1
        self.runCmd('devtool modify virtual/kernel -x %s' % tempdir)
        self.assertExists(os.path.join(tempdir, 'Makefile'), 'Extracted source could not be found')
        #Step 4.2
        configfile = os.path.join(tempdir,'.config')
        diff = self.runCmd('diff %s %s' % (tmpconfig, configfile))
        self.assertEqual(0,diff.status,'Kernel .config file is not the same using bitbake and devtool')
        #Step 4.3
        #NOTE: virtual/kernel is mapped to kernel_provider
        result = self.runCmd('devtool build %s' % kernel_provider)
        self.assertEqual(0,result.status,'Cannot build kernel using `devtool build`')
        kernelfile = os.path.join(self.get_bb_var('KBUILD_OUTPUT', kernel_provider), 'vmlinux')
        self.assertExists(kernelfile, 'Kernel was not build correctly')

        #Modify the kernel source
        modfile = os.path.join(tempdir,'arch/x86/boot/header.S')
        modstring = "Use a boot loader. Devtool testing."
        modapplied = self.runCmd("sed -i 's/Use a boot loader./%s/' %s" % (modstring, modfile))
        self.assertEqual(0,modapplied.status,'Modification to %s on kernel source failed' % modfile)
        #Modify the configuration
        codeconfigfile = os.path.join(tempdir,'.config.new')
        modconfopt = "CONFIG_SG_POOL=n"
        modconf = self.runCmd("sed -i 's/CONFIG_SG_POOL=y/%s/' %s" % (modconfopt, codeconfigfile))
        self.assertEqual(0,modconf.status,'Modification to %s failed' % codeconfigfile)
        #Build again kernel with devtool
        rebuild = self.runCmd('devtool build %s' % kernel_provider)
        self.assertEqual(0,rebuild.status,'Fail to build kernel after modification of source and config')
        #Step 4.4
        bzimagename = 'bzImage-' + self.get_bb_var('KERNEL_VERSION_NAME', kernel_provider)
        bzimagefile = os.path.join(self.get_bb_var('D', kernel_provider),'boot', bzimagename)
        checkmodcode = self.runCmd("grep '%s' %s" % (modstring, bzimagefile))
        self.assertEqual(0,checkmodcode.status,'Modification on kernel source failed')
        #Step 4.5
        checkmodconfg = self.runCmd("grep %s %s" % (modconfopt, codeconfigfile))
        self.assertEqual(0,checkmodconfg.status,'Modification to configuration file failed')
