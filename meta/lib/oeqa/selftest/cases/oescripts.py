from oeqa.selftest.case import OESelftestTestCase
from oeqa.selftest.cases.buildhistory import BuildhistoryBase
from oeqa.core.decorator.oeid import OETestID

class BuildhistoryDiffTests(BuildhistoryBase):
    _use_own_builddir = True
    _main_thread = False

    @OETestID(295)
    def test_buildhistory_diff(self):
        target = 'xcursor-transparent-theme'
        self.run_buildhistory_operation(target, target_config="PR = \"r1\"", change_bh_location=True)
        self.run_buildhistory_operation(target, target_config="PR = \"r0\"", change_bh_location=False, expect_error=True)
        result = self.runCmd("buildhistory-diff -p %s" % self.get_bb_var('BUILDHISTORY_DIR'))
        expected_output = 'PR changed from "r1" to "r0"'
        self.assertTrue(expected_output in result.output, msg="Did not find expected output: %s" % result.output)
