# Copyright (C) 2013-2017 Intel Corporation
# Released under the MIT license (see COPYING.MIT)

import sys
import os
import shutil
import glob
import errno
import re
from unittest.util import safe_repr

import oeqa.utils.ftools as ftools
from oeqa.utils.commands import runCmd, bitbake, get_bb_env, get_bb_var, get_bb_vars
from oeqa.core.case import OETestCase

class OESelftestTestCase(OETestCase):
    _use_own_builddir = False
    _main_thread = True
    _end_thread = False

    def __init__(self, methodName="runTest"):
        self._extra_tear_down_commands = []
        super(OESelftestTestCase, self).__init__(methodName)

    @classmethod
    def _setUpBuildDir(cls):
        if cls._use_own_builddir:
            cls.builddir = os.path.join(cls.tc.config_paths['base_builddir'],
                    cls.__module__, cls.__name__)

            cls.localconf_path = os.path.join(cls.builddir, "conf/local.conf")
            cls.localconf_backup = os.path.join(cls.builddir,
                    "conf/local.conf.bk")
            cls.local_bblayers_path = os.path.join(cls.builddir,
                    "conf/bblayers.conf")
            cls.local_bblayers_backup = os.path.join(cls.builddir,
                    "conf/bblayers.conf.bk")
        else:
            cls.builddir = cls.tc.config_paths['builddir']
            cls.localconf_path = cls.tc.config_paths['localconf']
            cls.localconf_backup = cls.tc.config_paths['localconf_class_backup']
            cls.local_bblayers_path = cls.tc.config_paths['bblayers']
            cls.local_bblayers_backup = \
                    cls.tc.config_paths['bblayers_class_backup']

        cls.testinc_path = os.path.join(cls.builddir, "conf/selftest.inc")
        cls.testinc_bblayers_path = os.path.join(cls.builddir,
                "conf/bblayers.inc")
        cls.machineinc_path = os.path.join(cls.builddir, "conf/machine.inc")

        # creates a custom build directory for every test class
        if not os.path.exists(cls.builddir):
            os.makedirs(cls.builddir)

            builddir_conf = os.path.join(cls.builddir, 'conf')
            os.makedirs(builddir_conf)
            shutil.copyfile(cls.tc.config_paths['localconf_backup'],
                    cls.localconf_path)
            shutil.copyfile(cls.tc.config_paths['bblayers_backup'],
                    cls.local_bblayers_path)

            ftools.append_file(cls.localconf_path, "\n# added by oe-selftest base class\n")
            ftools.append_file(cls.local_bblayers_path, "\n# added by oe-selftest base class\n")

            # shares original sstate_dir across build directories to speed up
            sstate_line = "SSTATE_DIR?=\"%s\"" % cls.td['SSTATE_DIR']
            ftools.append_file(cls.localconf_path, sstate_line)

            # shares original dl_dir across build directories to avoid additional
            # network usage
            dldir_line = "DL_DIR?=\"%s\"" % cls.td['DL_DIR']
            ftools.append_file(cls.localconf_path, dldir_line)

            # use the same value of threads for BB_NUMBER_THREADS/PARALLEL_MAKE
            # to avoid ran out resources (cpu/memory)
            if hasattr(cls.tc.loader, 'process_num'):
                ftools.append_file(cls.localconf_path, "BB_NUMBER_THREADS?=\"%d\"" %
                        cls.tc.loader.process_num)
                ftools.append_file(cls.localconf_path, "PARALLEL_MAKE?=\"-j %d\"" %
                        cls.tc.loader.process_num)

    @classmethod
    def setUpClass(cls):
        super(OESelftestTestCase, cls).setUpClass()

        cls.testlayer_path = cls.tc.config_paths['testlayer_path']
        cls._setUpBuildDir()

        cls._track_for_cleanup = [
            cls.testinc_path, cls.testinc_bblayers_path,
            cls.machineinc_path, cls.localconf_backup,
            cls.local_bblayers_backup]

        cls.add_include()

    @classmethod
    def tearDownClass(cls):
        cls.remove_include()
        cls.remove_inc_files()
        super(OESelftestTestCase, cls).tearDownClass()

    @classmethod
    def add_include(cls):
        if "#include added by oe-selftest" \
            not in ftools.read_file(cls.localconf_path):
                ftools.append_file(cls.localconf_path, \
                        "\n#include added by oe-selftest\ninclude machine.inc\ninclude selftest.inc")

        if "#include added by oe-selftest" \
            not in ftools.read_file(cls.local_bblayers_path):
                ftools.append_file(cls.local_bblayers_path, \
                        "\n#include added by oe-selftest\ninclude bblayers.inc")

    @classmethod
    def remove_include(cls):
        if "#include added by oe-selftest.py" \
            in ftools.read_file(cls.localconf_path):
                ftools.remove_from_file(cls.localconf_path, \
                        "\n#include added by oe-selftest.py\ninclude machine.inc\ninclude selftest.inc")

        if "#include added by oe-selftest.py" \
            in ftools.read_file(cls.local_bblayers_path):
                ftools.remove_from_file(cls.local_bblayers_path, \
                        "\n#include added by oe-selftest.py\ninclude bblayers.inc")

    @classmethod
    def remove_inc_files(cls):
        try:
            os.remove(cls.testinc_path)
            for root, _, files in os.walk(cls.testlayer_path):
                for f in files:
                    if f == 'test_recipe.inc':
                        os.remove(os.path.join(root, f))
        except OSError as e:
            pass

        for incl_file in ['conf/bblayers.inc', 'conf/machine.inc']:
            try:
                os.remove(os.path.join(cls.builddir, incl_file))
            except:
                pass

    def setUp(self):
        super(OESelftestTestCase, self).setUp()

        # Check if local.conf or bblayers.conf files backup exists
        # from a previous failed test and restore them
        if os.path.isfile(self.localconf_backup) or os.path.isfile(
                self.local_bblayers_backup):
            self.logger.debug("\
Found a local.conf and/or bblayers.conf backup from a previously aborted test.\
Restoring these files now, but tests should be re-executed from a clean environment\
to ensure accurate results.")
            try:
                shutil.copyfile(self.localconf_backup, self.localconf_path)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
            try:
                shutil.copyfile(self.local_bblayers_backup,
                                self.local_bblayers_path)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise
        else:
            # backup local.conf and bblayers.conf
            shutil.copyfile(self.localconf_path, self.localconf_backup)
            shutil.copyfile(self.local_bblayers_path, self.local_bblayers_backup)
            self.logger.debug("Creating local.conf and bblayers.conf backups.")
        # we don't know what the previous test left around in config or inc files
        # if it failed so we need a fresh start
        try:
            os.remove(self.testinc_path)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
        for root, _, files in os.walk(self.testlayer_path):
            for f in files:
                if f == 'test_recipe.inc':
                    os.remove(os.path.join(root, f))

        for incl_file in [self.testinc_bblayers_path, self.machineinc_path]:
            try:
                os.remove(incl_file)
            except OSError as e:
                if e.errno != errno.ENOENT:
                    raise

        if self.tc.custommachine:
            machine_conf = 'MACHINE ??= "%s"\n' % self.tc.custommachine
            self.set_machine_config(machine_conf)

        # tests might need their own setup
        # but if they overwrite this one they have to call
        # super each time, so let's give them an alternative
        self.setUpLocal()

    def setUpLocal(self):
        pass

    def tearDown(self):
        if self._extra_tear_down_commands:
            failed_extra_commands = []
            for command in self._extra_tear_down_commands:
                result = self.runCmd(command, ignore_status=True)
                if not result.status ==  0:
                    failed_extra_commands.append(command)
            if failed_extra_commands:
                self.logger.warning("tearDown commands have failed: %s" % ', '.join(map(str, failed_extra_commands)))
                self.logger.debug("Trying to move on.")
            self._extra_tear_down_commands = []

        if self._track_for_cleanup:
            for path in self._track_for_cleanup:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                if os.path.isfile(path):
                    os.remove(path)
            self._track_for_cleanup = []

        self.tearDownLocal()
        super(OESelftestTestCase, self).tearDown()

    def tearDownLocal(self):
        pass

    def add_command_to_tearDown(self, command):
        """Add test specific commands to the tearDown method"""
        self.logger.debug("Adding command '%s' to tearDown for this test." % command)
        self._extra_tear_down_commands.append(command)

    def track_for_cleanup(self, path):
        """Add test specific files or directories to be removed in the tearDown method"""
        self.logger.debug("Adding path '%s' to be cleaned up when test is over" % path)
        self._track_for_cleanup.append(path)

    def write_config(self, data):
        """Write to <builddir>/conf/selftest.inc"""

        self.logger.debug("Writing to: %s\n%s\n" % (self.testinc_path, data))
        ftools.write_file(self.testinc_path, data)

        if self.tc.custommachine and 'MACHINE' in data:
            machine = get_bb_var('MACHINE')
            self.logger.warning('MACHINE overridden: %s' % machine)

    def append_config(self, data):
        """Append to <builddir>/conf/selftest.inc"""
        self.logger.debug("Appending to: %s\n%s\n" % (self.testinc_path, data))
        ftools.append_file(self.testinc_path, data)

        if self.tc.custommachine and 'MACHINE' in data:
            machine = get_bb_var('MACHINE')
            self.logger.warning('MACHINE overridden: %s' % machine)

    def remove_config(self, data):
        """Remove data from <builddir>/conf/selftest.inc"""
        self.logger.debug("Removing from: %s\n%s\n" % (self.testinc_path, data))
        ftools.remove_from_file(self.testinc_path, data)

    def write_recipeinc(self, recipe, data):
        """Write to meta-sefltest/recipes-test/<recipe>/test_recipe.inc"""
        inc_file = os.path.join(self.testlayer_path, 'recipes-test', recipe, 'test_recipe.inc')
        self.logger.debug("Writing to: %s\n%s\n" % (inc_file, data))
        ftools.write_file(inc_file, data)

    def append_recipeinc(self, recipe, data):
        """Append data to meta-sefltest/recipes-test/<recipe>/test_recipe.inc"""
        inc_file = os.path.join(self.testlayer_path, 'recipes-test', recipe, 'test_recipe.inc')
        self.logger.debug("Appending to: %s\n%s\n" % (inc_file, data))
        ftools.append_file(inc_file, data)

    def remove_recipeinc(self, recipe, data):
        """Remove data from meta-sefltest/recipes-test/<recipe>/test_recipe.inc"""
        inc_file = os.path.join(self.testlayer_path, 'recipes-test', recipe, 'test_recipe.inc')
        self.logger.debug("Removing from: %s\n%s\n" % (inc_file, data))
        ftools.remove_from_file(inc_file, data)

    def delete_recipeinc(self, recipe):
        """Delete meta-sefltest/recipes-test/<recipe>/test_recipe.inc file"""
        inc_file = os.path.join(self.testlayer_path, 'recipes-test', recipe, 'test_recipe.inc')
        self.logger.debug("Deleting file: %s" % inc_file)
        try:
            os.remove(inc_file)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    def write_bblayers_config(self, data):
        """Write to <builddir>/conf/bblayers.inc"""
        self.logger.debug("Writing to: %s\n%s\n" % (self.testinc_bblayers_path, data))
        ftools.write_file(self.testinc_bblayers_path, data)

    def append_bblayers_config(self, data):
        """Append to <builddir>/conf/bblayers.inc"""
        self.logger.debug("Appending to: %s\n%s\n" % (self.testinc_bblayers_path, data))
        ftools.append_file(self.testinc_bblayers_path, data)

    def remove_bblayers_config(self, data):
        """Remove data from <builddir>/conf/bblayers.inc"""
        self.logger.debug("Removing from: %s\n%s\n" % (self.testinc_bblayers_path, data))
        ftools.remove_from_file(self.testinc_bblayers_path, data)

    def set_machine_config(self, data):
        """Write to <builddir>/conf/machine.inc"""
        self.logger.debug("Writing to: %s\n%s\n" % (self.machineinc_path, data))
        ftools.write_file(self.machineinc_path, data)

    # check does path exist    
    def assertExists(self, expr, msg=None):
        if not os.path.exists(expr):
            msg = self._formatMessage(msg, "%s does not exist" % safe_repr(expr))
            raise self.failureException(msg)
    
    # check does path not exist 
    def assertNotExists(self, expr, msg=None):
        if os.path.exists(expr):
            msg = self._formatMessage(msg, "%s exists when it should not" % safe_repr(expr))

            raise self.failureException(msg)

    # utils commands to run on it's on builddir
    @classmethod 
    def _env_own_builddir(cls, **kwargs):
        env = None

        if 'env' in kwargs:
            env = kwargs['env']

            if not 'BUILDDIR' in env:
                env['BUILDDIR'] = cls.builddir
            if not 'BBPATH' in env:
                env['BBPATH'] = cls.builddir

        else:
            env = os.environ.copy()
            env['BUILDDIR'] = cls.builddir
            env['BBPATH'] = cls.builddir

        kwargs['env'] = env

        # XXX: tinfoil doesn't honor BBPATH bblayers and tinfoil test
        # modules uses it
        if not 'cwd' in kwargs:
            kwargs['cwd'] = cls.builddir

        # XXX: uncomment for debugging purposes
        #kwargs['output_log'] = cls.logger

        return kwargs

    @classmethod
    def runCmd(cls, *args, **kwargs):
        kwargs = cls._env_own_builddir(**kwargs)
        return runCmd(*args, **kwargs)

    @classmethod
    def bitbake(cls, *args, **kwargs):
        kwargs = cls._env_own_builddir(**kwargs)
        return bitbake(*args, **kwargs)

    @classmethod
    def get_bb_env(cls, target=None, postconfig=None):
        if target:
            return cls.bitbake("-e %s" % target, postconfig=postconfig).output
        else:
            return cls.bitbake("-e", postconfig=postconfig).output

    @classmethod
    def get_bb_vars(cls, variables=None, target=None, postconfig=None):
        """Get values of multiple bitbake variables"""
        bbenv = cls.get_bb_env(target, postconfig=postconfig)

        if variables is not None:
            variables = variables.copy()
        var_re = re.compile(r'^(export )?(?P<var>\w+(_.*)?)="(?P<value>.*)"$')
        unset_re = re.compile(r'^unset (?P<var>\w+)$')
        lastline = None
        values = {}
        for line in bbenv.splitlines():
            match = var_re.match(line)
            val = None
            if match:
                val = match.group('value')
            else:
                match = unset_re.match(line)
                if match:
                    # Handle [unexport] variables
                    if lastline.startswith('#   "'):
                        val = lastline.split('"')[1]
            if val:
                var = match.group('var')
                if variables is None:
                    values[var] = val
                else:
                    if var in variables:
                        values[var] = val
                        variables.remove(var)
                    # Stop after all required variables have been found
                    if not variables:
                        break
            lastline = line
        if variables:
            # Fill in missing values
            for var in variables:
                values[var] = None
        return values
    
    @classmethod 
    def get_bb_var(cls, var, target=None, postconfig=None):
        return cls.get_bb_vars([var], target, postconfig)[var]
