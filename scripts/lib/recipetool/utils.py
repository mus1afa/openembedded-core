# Recipe creation tool - utility functions
#
# Copyright (C) 2016-2017 Intel Corporation
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

def ensure_npm(tinfoil, fixed_setup=False):
    if not tinfoil.recipes_parsed:
        tinfoil.parse_recipes()
    try:
        rd = tinfoil.parse_recipe('nodejs-native')
    except bb.providers.NoProvider:
        if fixed_setup:
            msg = 'nodejs-native is required for npm but is not available within this SDK'
        else:
            msg = 'nodejs-native is required for npm but is not available - you will likely need to add a layer that provides nodejs'
        logger.error(msg)
        return None
    bindir = rd.getVar('STAGING_BINDIR_NATIVE')
    npmpath = os.path.join(bindir, 'npm')
    if not os.path.exists(npmpath):
        tinfoil.build_targets('nodejs-native', 'addto_recipe_sysroot')
        if not os.path.exists(npmpath):
            logger.error('npm required to process specified source, but nodejs-native did not seem to populate it')
            return None
    return bindir
