import os
import tempfile

from oeqa.selftest.case import OESelftestTestCase
from oeqa.core.decorator.oeid import OETestID

class LicenseTests(OESelftestTestCase):
    _use_own_builddir = True
    _main_thread = False

    # Verify that changing a license file that has an absolute path causes
    # the license qa to fail due to a mismatched md5sum.
    @OETestID(1197)
    def test_nonmatching_checksum(self):
        bitbake_cmd = '-c populate_lic emptytest'
        error_msg = 'emptytest: The new md5 checksum is 8d777f385d3dfec8815d20f7496026dc'

        lic_file, lic_path = tempfile.mkstemp()
        os.close(lic_file)
        self.track_for_cleanup(lic_path)

        self.write_recipeinc('emptytest', """
INHIBIT_DEFAULT_DEPS = "1"
LIC_FILES_CHKSUM = "file://%s;md5=d41d8cd98f00b204e9800998ecf8427e"
SRC_URI = "file://%s;md5=d41d8cd98f00b204e9800998ecf8427e"
""" % (lic_path, lic_path))
        result = self.bitbake(bitbake_cmd)

        with open(lic_path, "w") as f:
            f.write("data")

        self.write_config("INHERIT_remove = \"report-error\"")
        result = self.bitbake(bitbake_cmd, ignore_status=True)
        if error_msg not in result.output:
            raise AssertionError(result.output)
