# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for maas_wipe.py."""

__all__ = []

import argparse
import subprocess
import builtins
from textwrap import dedent
from unittest.mock import call, MagicMock

from maastesting.factory import factory
from maastesting.matchers import (
    MockCalledOnceWith,
    MockCallsMatch,
    MockNotCalled,
)
from maastesting.testcase import MAASTestCase
from snippets import maas_wipe
from snippets.maas_wipe import (
    get_disk_info,
    get_disk_security_info,
    list_disks,
    secure_erase_hdparm,
    try_secure_erase,
    install_nvme_cli,
    nvme_write_zeroes,
    wipe_quickly,
    WipeError,
    zero_disk,
)
# hdparm and nvme-cli outputs used in the tests
from snippets.tests.test_maas_wipe_defs import (
    HDPARM_BEFORE_SECURITY, HDPARM_AFTER_SECURITY,
    HDPARM_SECURITY_NOT_SUPPORTED,
    HDPARM_SECURITY_SUPPORTED_NOT_ENABLED,
    HDPARM_SECURITY_SUPPORTED_ENABLED,
    HDPARM_SECURITY_ALL_TRUE, NVME_IDCTRL_PROLOGUE,
    NVME_IDCTRL_OACS_FORMAT_SUPPORTED,
    NVME_IDCTRL_OACS_FORMAT_UNSUPPORTED,
    NVME_IDCTRL_ONCS_WRITEZ_SUPPORTED,
    NVME_IDCTRL_ONCS_WRITEZ_UNSUPPORTED,
    NVME_IDCTRL_FNA_CRYPTFORMAT_SUPPORTED,
    NVME_IDCTRL_FNA_CRYPTFORMAT_UNSUPPORTED,
    NVME_IDCTRL_EPILOGUE)


class TestMAASWipe(MAASTestCase):
    def setUp(self):
        super().setUp()
        self.print_flush = self.patch(maas_wipe, "print_flush")
        maas_wipe.nvme_cli_installed = True

    def make_empty_file(self, path, content=b"\0"):
        assert len(content) == 1
        # Make an empty 100 MiB file.
        buf = content * 1024 * 1024
        with open(path, "wb") as fp:
            for _ in range(5):
                fp.write(buf)

    def test_list_disks_calls_lsblk(self):
        mock_check_output = self.patch(subprocess, "check_output")
        mock_check_output.return_value = b""
        list_disks()
        self.assertThat(
            mock_check_output,
            MockCalledOnceWith(["lsblk", "-d", "-n", "-oKNAME,TYPE,RO"]),
        )

    def test_list_disks_returns_only_readwrite_disks(self):
        mock_check_output = self.patch(subprocess, "check_output")
        mock_check_output.return_value = dedent(
            """\
            sda   disk  0
            sdb   disk  1
            sr0   rom   0
            sr1   rom   0
            nvme0n1   disk  0
            nvme1n1   disk  1
            """
        ).encode("ascii")
        self.assertEqual([b"sda", b"nvme0n1"], list_disks())

    def test_get_disk_security_info_missing_hdparm(self):
        hdparm_output = HDPARM_BEFORE_SECURITY + HDPARM_AFTER_SECURITY
        mock_check_output = self.patch(subprocess, "check_output")
        mock_check_output.return_value = hdparm_output
        disk_name = factory.make_name("disk").encode("ascii")
        observered = get_disk_security_info(disk_name)
        self.assertThat(
            mock_check_output,
            MockCalledOnceWith([b"hdparm", b"-I", b"/dev/%s" % disk_name]),
        )
        self.assertEqual(
            {
                b"supported": False,
                b"enabled": False,
                b"locked": False,
                b"frozen": False,
            },
            observered,
        )

    def test_get_disk_security_info_not_supported_hdparm(self):
        hdparm_output = (
            HDPARM_BEFORE_SECURITY
            + HDPARM_SECURITY_NOT_SUPPORTED
            + HDPARM_AFTER_SECURITY
        )
        mock_check_output = self.patch(subprocess, "check_output")
        mock_check_output.return_value = hdparm_output
        disk_name = factory.make_name("disk").encode("ascii")
        observered = get_disk_security_info(disk_name)
        self.assertThat(
            mock_check_output,
            MockCalledOnceWith([b"hdparm", b"-I", b"/dev/%s" % disk_name]),
        )
        self.assertEqual(
            {
                b"supported": False,
                b"enabled": False,
                b"locked": False,
                b"frozen": False,
            },
            observered,
        )

    def test_get_disk_security_info_supported_not_enabled_hdparm(self):
        hdparm_output = (
            HDPARM_BEFORE_SECURITY
            + HDPARM_SECURITY_SUPPORTED_NOT_ENABLED
            + HDPARM_AFTER_SECURITY
        )
        mock_check_output = self.patch(subprocess, "check_output")
        mock_check_output.return_value = hdparm_output
        disk_name = factory.make_name("disk").encode("ascii")
        observered = get_disk_security_info(disk_name)
        self.assertThat(
            mock_check_output,
            MockCalledOnceWith([b"hdparm", b"-I", b"/dev/%s" % disk_name]),
        )
        self.assertEqual(
            {
                b"supported": True,
                b"enabled": False,
                b"locked": False,
                b"frozen": False,
            },
            observered,
        )

    def test_get_disk_security_info_supported_enabled_hdparm(self):
        hdparm_output = (
            HDPARM_BEFORE_SECURITY
            + HDPARM_SECURITY_SUPPORTED_ENABLED
            + HDPARM_AFTER_SECURITY
        )
        mock_check_output = self.patch(subprocess, "check_output")
        mock_check_output.return_value = hdparm_output
        disk_name = factory.make_name("disk").encode("ascii")
        observered = get_disk_security_info(disk_name)
        self.assertThat(
            mock_check_output,
            MockCalledOnceWith([b"hdparm", b"-I", b"/dev/%s" % disk_name]),
        )
        self.assertEqual(
            {
                b"supported": True,
                b"enabled": True,
                b"locked": False,
                b"frozen": False,
            },
            observered,
        )

    def test_get_disk_security_info_all_true_hdparm(self):
        hdparm_output = (
            HDPARM_BEFORE_SECURITY
            + HDPARM_SECURITY_ALL_TRUE
            + HDPARM_AFTER_SECURITY
        )
        mock_check_output = self.patch(subprocess, "check_output")
        mock_check_output.return_value = hdparm_output
        disk_name = factory.make_name("disk").encode("ascii")
        observered = get_disk_security_info(disk_name)
        self.assertThat(
            mock_check_output,
            MockCalledOnceWith([b"hdparm", b"-I", b"/dev/%s" % disk_name]),
        )
        self.assertEqual(
            {
                b"supported": True,
                b"enabled": True,
                b"locked": True,
                b"frozen": True,
            },
            observered,
        )

    def test_get_disk_info_hdparm(self):
        disk_names = [
            factory.make_name("disk").encode("ascii") for _ in range(3)
        ]
        self.patch(maas_wipe, "list_disks").return_value = disk_names
        security_info = [
            {
                b"supported": True,
                b"enabled": True,
                b"locked": True,
                b"frozen": True,
            }
            for _ in range(3)
        ]
        self.patch(
            maas_wipe, "get_hdparm_security_info"
        ).side_effect = security_info
        observed = get_disk_info()
        self.assertEqual(
            {disk_names[i]: security_info[i] for i in range(3)}, observed
        )

    def test_install_nvme_cli_success(self):
        class SubprocessReturn:
            returncode = 0

        # Set nvme_cli_installed to its start value (False)
        maas_wipe.nvme_cli_installed = False

        mock_run = self.patch(subprocess, "run")
        mock_return = SubprocessReturn()
        mock_run.return_value = mock_return

        install_nvme_cli()
        self.assertThat
        (
            mock_run,
            MockCalledOnceWith("DEBIAN_FRONTEND=noninteractive apt-get install -y nvme-cli",
                               executable="/bin/bash", shell=True, stdin=None),
        )

        # Given that nvme_cli_installed is True after this test, we're ok
        # with the following tests that requires it to be True.
        self.assertEqual(maas_wipe.nvme_cli_installed, True)

    def test_install_nvme_cli_failed(self):
        class SubprocessReturn:
            returncode = 0

        # Set nvme_cli_installed to its start value (False)
        maas_wipe.nvme_cli_installed = False

        mock_run = self.patch(subprocess, "run")
        mock_return = SubprocessReturn()
        mock_return.returncode = 100
        mock_run.return_value = mock_return

        install_nvme_cli()
        self.assertThat(
            mock_run,
            MockCalledOnceWith("DEBIAN_FRONTEND=noninteractive apt-get install -y nvme-cli",
                               executable="/bin/bash", shell=True, stdin=None),
        )

        # In this test nvme_cli_installed ends-up being False, so we need
        # to manually set it as True after the test, due to some following
        # tests requiring it to be True.
        self.assertEqual(maas_wipe.nvme_cli_installed, False)
        maas_wipe.nvme_cli_installed = True

    def test_get_disk_security_info_crypt_format_writez_nvme(self):
        nvme_cli_output = (NVME_IDCTRL_PROLOGUE
                           + NVME_IDCTRL_OACS_FORMAT_SUPPORTED
                           + NVME_IDCTRL_ONCS_WRITEZ_SUPPORTED
                           + NVME_IDCTRL_FNA_CRYPTFORMAT_SUPPORTED
                           + NVME_IDCTRL_EPILOGUE
                           )
        mock_check_output = self.patch(subprocess, "check_output")
        mock_check_output.return_value = nvme_cli_output
        disk_name = factory.make_name("nvme").encode("ascii")
        observered = get_disk_security_info(disk_name)
        self.assertThat(
            mock_check_output,
            MockCallsMatch(call(["nvme", "id-ctrl", maas_wipe.DEV_PATH % disk_name]),
                           call(["nvme", "id-ns", maas_wipe.DEV_PATH % disk_name]))
        )
        self.assertEqual(
            {
                "format_supported": True,
                "writez_supported": True,
                "crypto_format": True,
                "nsze": 0,
                "lbaf": 0,
                "ms": 0,
            },
            observered,
        )

    def test_get_disk_security_info_nocrypt_format_writez_nvme(self):
        nvme_cli_output = (NVME_IDCTRL_PROLOGUE
                           + NVME_IDCTRL_OACS_FORMAT_SUPPORTED
                           + NVME_IDCTRL_ONCS_WRITEZ_SUPPORTED
                           + NVME_IDCTRL_FNA_CRYPTFORMAT_UNSUPPORTED
                           + NVME_IDCTRL_EPILOGUE
                           )
        mock_check_output = self.patch(subprocess, "check_output")
        mock_check_output.return_value = nvme_cli_output
        disk_name = factory.make_name("nvme").encode("ascii")
        observered = get_disk_security_info(disk_name)
        self.assertThat(
            mock_check_output,
            MockCallsMatch(call(["nvme", "id-ctrl", maas_wipe.DEV_PATH % disk_name]),
                           call(["nvme", "id-ns", maas_wipe.DEV_PATH % disk_name]))
        )
        self.assertEqual(
            {
                "format_supported": True,
                "writez_supported": True,
                "crypto_format": False,
                "nsze": 0,
                "lbaf": 0,
                "ms": 0,
            },
            observered,
        )

    def test_get_disk_security_info_crypt_format_nowritez_nvme(self):
        nvme_cli_output = (NVME_IDCTRL_PROLOGUE
                           + NVME_IDCTRL_OACS_FORMAT_SUPPORTED
                           + NVME_IDCTRL_ONCS_WRITEZ_UNSUPPORTED
                           + NVME_IDCTRL_FNA_CRYPTFORMAT_SUPPORTED
                           + NVME_IDCTRL_EPILOGUE
                           )
        mock_check_output = self.patch(subprocess, "check_output")
        mock_check_output.return_value = nvme_cli_output
        disk_name = factory.make_name("nvme").encode("ascii")
        observered = get_disk_security_info(disk_name)
        self.assertThat(
            mock_check_output,
            MockCallsMatch(call(["nvme", "id-ctrl", maas_wipe.DEV_PATH % disk_name]),
                           call(["nvme", "id-ns", maas_wipe.DEV_PATH % disk_name]))
        )
        self.assertEqual(
            {
                "format_supported": True,
                "writez_supported": False,
                "crypto_format": True,
                "nsze": 0,
                "lbaf": 0,
                "ms": 0,
            },
            observered,
        )

    def test_get_disk_security_info_noformat_writez_nvme(self):
        nvme_cli_output = (NVME_IDCTRL_PROLOGUE
                           + NVME_IDCTRL_OACS_FORMAT_UNSUPPORTED
                           + NVME_IDCTRL_ONCS_WRITEZ_SUPPORTED
                           + NVME_IDCTRL_FNA_CRYPTFORMAT_SUPPORTED
                           + NVME_IDCTRL_EPILOGUE
                           )
        mock_check_output = self.patch(subprocess, "check_output")
        mock_check_output.return_value = nvme_cli_output
        disk_name = factory.make_name("nvme").encode("ascii")
        observered = get_disk_security_info(disk_name)
        self.assertThat(
            mock_check_output,
            MockCallsMatch(call(["nvme", "id-ctrl", maas_wipe.DEV_PATH % disk_name]),
                           call(["nvme", "id-ns", maas_wipe.DEV_PATH % disk_name]))
        )
        self.assertEqual(
            {
                "format_supported": False,
                "writez_supported": True,
                "crypto_format": True,
                "nsze": 0,
                "lbaf": 0,
                "ms": 0,
            },
            observered,
        )

    def test_get_disk_security_info_noformat_nowritez_nvme(self):
        nvme_cli_output = (NVME_IDCTRL_PROLOGUE
                           + NVME_IDCTRL_OACS_FORMAT_UNSUPPORTED
                           + NVME_IDCTRL_ONCS_WRITEZ_UNSUPPORTED
                           + NVME_IDCTRL_FNA_CRYPTFORMAT_UNSUPPORTED
                           + NVME_IDCTRL_EPILOGUE
                           )
        mock_check_output = self.patch(subprocess, "check_output")
        mock_check_output.return_value = nvme_cli_output
        disk_name = factory.make_name("nvme").encode("ascii")
        observered = get_disk_security_info(disk_name)
        self.assertThat(
            mock_check_output,
            MockCallsMatch(call(["nvme", "id-ctrl", maas_wipe.DEV_PATH % disk_name]),
                           call(["nvme", "id-ns", maas_wipe.DEV_PATH % disk_name]))
        )
        self.assertEqual(
            {
                "format_supported": False,
                "writez_supported": False,
                "crypto_format": False,
                "nsze": 0,
                "lbaf": 0,
                "ms": 0,
            },
            observered,
        )

    def test_get_disk_info_nvme(self):
        disk_names = [
            factory.make_name("nvme").encode("ascii") for _ in range(3)
        ]
        self.patch(maas_wipe, "list_disks").return_value = disk_names
        security_info = [
            {
                "format_supported": True,
                "writez_supported": True,
                "crypto_format": True,
                "nsze": 0,
                "lbaf": 0,
                "ms": 0,
            }
            for _ in range(3)
        ]
        self.patch(
            maas_wipe, "get_nvme_security_info"
        ).side_effect = security_info
        observed = get_disk_info()
        self.assertEqual(
            {disk_names[i]: security_info[i] for i in range(3)}, observed
        )

    def test_try_secure_erase_not_supported_hdparm(self):
        disk_name = factory.make_name("disk").encode("ascii")
        disk_info = {
            b"supported": False,
            b"enabled": False,
            b"locked": False,
            b"frozen": False,
        }
        self.assertFalse(try_secure_erase(disk_name, disk_info))
        self.assertThat(
            self.print_flush,
            MockCalledOnceWith(
                "%s: drive does not support secure erase."
                % (disk_name.decode("ascii"))
            ),
        )

    def test_try_secure_erase_frozen_hdparm(self):
        disk_name = factory.make_name("disk").encode("ascii")
        disk_info = {
            b"supported": True,
            b"enabled": False,
            b"locked": False,
            b"frozen": True,
        }
        self.assertFalse(try_secure_erase(disk_name, disk_info))
        self.assertThat(
            self.print_flush,
            MockCalledOnceWith(
                "%s: not using secure erase; drive is currently frozen."
                % (disk_name.decode("ascii"))
            ),
        )

    def test_try_secure_erase_locked_hdparm(self):
        disk_name = factory.make_name("disk").encode("ascii")
        disk_info = {
            b"supported": True,
            b"enabled": False,
            b"locked": True,
            b"frozen": False,
        }
        self.assertFalse(try_secure_erase(disk_name, disk_info))
        self.assertThat(
            self.print_flush,
            MockCalledOnceWith(
                "%s: not using secure erase; drive is currently locked."
                % (disk_name.decode("ascii"))
            ),
        )

    def test_try_secure_erase_enabled_hdparm(self):
        disk_name = factory.make_name("disk").encode("ascii")
        disk_info = {
            b"supported": True,
            b"enabled": True,
            b"locked": False,
            b"frozen": False,
        }
        self.assertFalse(try_secure_erase(disk_name, disk_info))
        self.assertThat(
            self.print_flush,
            MockCalledOnceWith(
                "%s: not using secure erase; drive security "
                "is already enabled." % (disk_name.decode("ascii"))
            ),
        )

    def test_try_secure_erase_failed_erase_hdparm(self):
        disk_name = factory.make_name("disk").encode("ascii")
        disk_info = {
            b"supported": True,
            b"enabled": False,
            b"locked": False,
            b"frozen": False,
        }
        exception = factory.make_exception()
        self.patch(maas_wipe, "secure_erase_hdparm").side_effect = exception
        self.assertFalse(try_secure_erase(disk_name, disk_info))
        self.assertThat(
            self.print_flush,
            MockCalledOnceWith(
                "%s: failed to be securely erased: %s"
                % (disk_name.decode("ascii"), exception)
            ),
        )

    def test_try_secure_erase_successful_erase_hdparm(self):
        disk_name = factory.make_name("disk").encode("ascii")
        disk_info = {
            b"supported": True,
            b"enabled": False,
            b"locked": False,
            b"frozen": False,
        }
        self.patch(maas_wipe, "secure_erase_hdparm")
        self.assertTrue(try_secure_erase(disk_name, disk_info))
        self.assertThat(
            self.print_flush,
            MockCalledOnceWith(
                "%s: successfully securely erased."
                % (disk_name.decode("ascii"))
            ),
        )

    def test_try_secure_erase_not_supported_nvme(self):
        disk_name = factory.make_name("nvme").encode("ascii")
        sec_info = {
            "format_supported": False,
            "writez_supported": True,
            "crypto_format": True,
            "nsze": 0,
            "lbaf": 0,
            "ms": 0,
        }
        self.assertFalse(try_secure_erase(disk_name, sec_info))
        self.assertThat(
            self.print_flush,
            MockCalledOnceWith(
                "Device %s does not support formatting"
                % disk_name.decode("ascii")
            ),
        )

    def test_try_secure_erase_successful_cryto_nvme(self):
        disk_name = factory.make_name("nvme").encode("ascii")
        sec_info = {
            "format_supported": True,
            "writez_supported": True,
            "crypto_format": True,
            "nsze": 0,
            "lbaf": 0,
            "ms": 0,
        }
        mock_check_output = self.patch(subprocess, "check_output")
        self.assertTrue(try_secure_erase(disk_name, sec_info))
        self.assertThat(
            mock_check_output,
            MockCalledOnceWith(["nvme", "format", "-s", "2", "-l", "0",
                                "-m", "0", maas_wipe.DEV_PATH % disk_name]

                               ),
        )
        self.assertThat(
            self.print_flush,
            MockCalledOnceWith(
                "Secure erase was successful on NVMe drive %s"
                % disk_name.decode("ascii")
            ),
        )

    def test_try_secure_erase_successful_nocryto_nvme(self):
        disk_name = factory.make_name("nvme").encode("ascii")
        sec_info = {
            "format_supported": True,
            "writez_supported": True,
            "crypto_format": False,
            "nsze": 0,
            "lbaf": 0,
            "ms": 0,
        }
        mock_check_output = self.patch(subprocess, "check_output")
        self.assertTrue(try_secure_erase(disk_name, sec_info))
        self.assertThat(
            mock_check_output,
            MockCalledOnceWith(["nvme", "format", "-s", "1", "-l", "0",
                                "-m", "0", maas_wipe.DEV_PATH % disk_name]

                               ),
        )
        self.assertThat(
            self.print_flush,
            MockCalledOnceWith(
                "Secure erase was successful on NVMe drive %s"
                % disk_name.decode("ascii")
            ),
        )

    def test_try_secure_erase_failed_nvme(self):
        disk_name = factory.make_name("nvme").encode("ascii")
        sec_info = {
            "format_supported": True,
            "writez_supported": True,
            "crypto_format": True,
            "nsze": 0,
            "lbaf": 0,
            "ms": 0,
        }
        mock_check_output = self.patch(subprocess, "check_output")
        mock_check_output.side_effect = subprocess.CalledProcessError(1, "nvme format ...")

        self.assertFalse(try_secure_erase(disk_name, sec_info))
        self.assertThat(
            self.print_flush,
            MockCalledOnceWith(
                "\nError with format command (%s)" % "1"
            ),
        )

    def test_try_write_zeroes_not_supported_nvme(self):
        disk_name = factory.make_name("nvme").encode("ascii")
        sec_info = {
            "format_supported": False,
            "writez_supported": False,
            "crypto_format": False,
            "nsze": 100,
            "lbaf": 0,
            "ms": 0,
        }
        mock_print = self.patch(builtins, "print")
        self.assertFalse(nvme_write_zeroes(disk_name, sec_info))
        self.assertThat(
            mock_print,
            MockCalledOnceWith(
                "NVMe drive %s does not support write-zeroes"
                % disk_name.decode("ascii")
            ),
        )
        self.assertThat(
            self.print_flush,
            MockCalledOnceWith("Will fallback to regular drive zeroing."
                               ),
        )

    def test_try_write_zeroes_supported_invalid_nsze_nvme(self):
        disk_name = factory.make_name("nvme").encode("ascii")
        sec_info = {
            "format_supported": False,
            "writez_supported": True,
            "crypto_format": False,
            "nsze": 0,
            "lbaf": 0,
            "ms": 0,
        }
        mock_print = self.patch(builtins, "print")
        self.assertFalse(nvme_write_zeroes(disk_name, sec_info))
        self.assertThat(
            mock_print,
            MockCalledOnceWith(
                "Bad namespace information collected on NVMe drive %s"
                % disk_name.decode("ascii")
            ),
        )
        self.assertThat(
            self.print_flush,
            MockCalledOnceWith("Will fallback to regular drive zeroing."
                               ),
        )

    def test_try_write_zeroes_successful_nvme(self):
        disk_name = factory.make_name("nvme").encode("ascii")
        sec_info = {
            "format_supported": False,
            "writez_supported": True,
            "crypto_format": False,
            "nsze": 0x100a,
            "lbaf": 0,
            "ms": 0,
        }
        mock_check_output = self.patch(subprocess, "check_output")
        self.assertTrue(nvme_write_zeroes(disk_name, sec_info))
        self.assertThat(
            mock_check_output,
            MockCalledOnceWith(["nvme", "write-zeroes", "-f", "-s", "0", "-c",
                                "100a", maas_wipe.DEV_PATH % disk_name]

                               ),
        )
        self.assertThat(
            self.print_flush,
            MockCalledOnceWith("%s: successfully zeroed (using write-zeroes)."
                               % disk_name.decode("ascii")
                               ),
        )

    def test_try_write_zeroes_failed_nvme(self):
        disk_name = factory.make_name("nvme").encode("ascii")
        sec_info = {
            "format_supported": False,
            "writez_supported": True,
            "crypto_format": False,
            "nsze": 100,
            "lbaf": 0,
            "ms": 0,
        }
        mock_check_output = self.patch(subprocess, "check_output")
        mock_check_output.side_effect = subprocess.CalledProcessError(1, "nvme write-zeroes ...")

        self.assertFalse(nvme_write_zeroes(disk_name, sec_info))
        self.assertThat(
            self.print_flush,
            MockCalledOnceWith(
                "\nError with write-zeroes command (%s)" % "1"
            ),
        )

    def test_secure_erase_writes_known_data_hdparm(self):
        tmp_dir = self.make_dir()
        dev_path = (tmp_dir + "/%s").encode("ascii")
        self.patch(maas_wipe, "DEV_PATH", dev_path)
        dev_name = factory.make_name("disk").encode("ascii")
        file_path = dev_path % dev_name
        self.make_empty_file(file_path)

        # Fail at the set-pass to stop the function.
        mock_check_output = self.patch(subprocess, "check_output")
        mock_check_output.side_effect = factory.make_exception()

        self.assertRaises(WipeError, secure_erase_hdparm, dev_name)
        expected_buf = b"M" * 1024 * 1024
        with open(file_path, "rb") as fp:
            read_buf = fp.read(len(expected_buf))
        self.assertEqual(
            expected_buf, read_buf, "First 1 MiB of file was not written."
        )

    def test_secure_erase_sets_security_password_hdparm(self):
        tmp_dir = self.make_dir()
        dev_path = (tmp_dir + "/%s").encode("ascii")
        self.patch(maas_wipe, "DEV_PATH", dev_path)
        dev_name = factory.make_name("disk").encode("ascii")
        file_path = dev_path % dev_name
        self.make_empty_file(file_path)

        mock_check_output = self.patch(subprocess, "check_output")

        # Fail to get disk info just to exit early.
        exception_type = factory.make_exception_type()
        self.patch(
            maas_wipe, "get_hdparm_security_info"
        ).side_effect = exception_type()

        self.assertRaises(exception_type, secure_erase_hdparm, dev_name)
        self.assertThat(
            mock_check_output,
            MockCalledOnceWith(
                [
                    b"hdparm",
                    b"--user-master",
                    b"u",
                    b"--security-set-pass",
                    b"maas",
                    file_path,
                ]
            ),
        )

    def test_secure_erase_fails_if_not_enabled_hdparm(self):
        tmp_dir = self.make_dir()
        dev_path = (tmp_dir + "/%s").encode("ascii")
        self.patch(maas_wipe, "DEV_PATH", dev_path)
        dev_name = factory.make_name("disk").encode("ascii")
        file_path = dev_path % dev_name
        self.make_empty_file(file_path)

        self.patch(subprocess, "check_output")
        self.patch(maas_wipe, "get_hdparm_security_info").return_value = {
            b"enabled": False
        }

        error = self.assertRaises(WipeError, secure_erase_hdparm, dev_name)
        self.assertEqual(
            "Failed to enable security to perform secure erase.", str(error)
        )

    def test_secure_erase_fails_when_still_enabled_hdparm(self):
        tmp_dir = self.make_dir()
        dev_path = (tmp_dir + "/%s").encode("ascii")
        self.patch(maas_wipe, "DEV_PATH", dev_path)
        dev_name = factory.make_name("disk").encode("ascii")
        file_path = dev_path % dev_name
        self.make_empty_file(file_path)

        mock_check_output = self.patch(subprocess, "check_output")
        self.patch(maas_wipe, "get_hdparm_security_info").return_value = {
            b"enabled": True
        }
        exception = factory.make_exception()
        mock_check_call = self.patch(subprocess, "check_call")
        mock_check_call.side_effect = exception

        error = self.assertRaises(WipeError, secure_erase_hdparm, dev_name)
        self.assertThat(
            mock_check_call,
            MockCalledOnceWith(
                [
                    b"hdparm",
                    b"--user-master",
                    b"u",
                    b"--security-erase",
                    b"maas",
                    file_path,
                ]
            ),
        )
        self.assertThat(
            mock_check_output,
            MockCallsMatch(
                call(
                    [
                        b"hdparm",
                        b"--user-master",
                        b"u",
                        b"--security-set-pass",
                        b"maas",
                        file_path,
                    ]
                ),
                call([b"hdparm", b"--security-disable", b"maas", file_path]),
            ),
        )
        self.assertEqual("Failed to securely erase.", str(error))
        self.assertEqual(exception, error.__cause__)

    def test_secure_erase_fails_when_buffer_not_different_hdparm(self):
        tmp_dir = self.make_dir()
        dev_path = (tmp_dir + "/%s").encode("ascii")
        self.patch(maas_wipe, "DEV_PATH", dev_path)
        dev_name = factory.make_name("disk").encode("ascii")
        file_path = dev_path % dev_name
        self.make_empty_file(file_path)

        self.patch(subprocess, "check_output")
        self.patch(maas_wipe, "get_hdparm_security_info").side_effect = [
            {b"enabled": True},
            {b"enabled": False},
        ]
        mock_check_call = self.patch(subprocess, "check_call")

        error = self.assertRaises(WipeError, secure_erase_hdparm, dev_name)
        self.assertThat(
            mock_check_call,
            MockCalledOnceWith(
                [
                    b"hdparm",
                    b"--user-master",
                    b"u",
                    b"--security-erase",
                    b"maas",
                    file_path,
                ]
            ),
        )
        self.assertEqual(
            "Secure erase was performed, but failed to actually work.",
            str(error),
        )

    def test_secure_erase_fails_success_hdparm(self):
        tmp_dir = self.make_dir()
        dev_path = (tmp_dir + "/%s").encode("ascii")
        self.patch(maas_wipe, "DEV_PATH", dev_path)
        dev_name = factory.make_name("disk").encode("ascii")
        file_path = dev_path % dev_name
        self.make_empty_file(file_path)

        self.patch(subprocess, "check_output")
        self.patch(maas_wipe, "get_hdparm_security_info").side_effect = [
            {b"enabled": True},
            {b"enabled": False},
        ]

        def wipe_buffer(*args, **kwargs):
            # Write the first 1 MiB to zeros so it looks like the device
            # has been securely erased.
            buf = b"\0" * 1024 * 1024
            with open(file_path, "wb") as fp:
                fp.write(buf)

        mock_check_call = self.patch(subprocess, "check_call")
        mock_check_call.side_effect = wipe_buffer

        # No error should be raised.
        secure_erase_hdparm(dev_name)

    def test_wipe_quickly(self):
        tmp_dir = self.make_dir()
        dev_path = (tmp_dir + "/%s").encode("ascii")
        self.patch(maas_wipe, "DEV_PATH", dev_path)
        dev_name = factory.make_name("disk").encode("ascii")
        file_path = dev_path % dev_name
        self.make_empty_file(file_path, content=b"T")

        wipe_quickly(dev_name)

        buf_size = 1024 * 1024
        with open(file_path, "rb") as fp:
            first_buf = fp.read(buf_size)
            fp.seek(-buf_size, 2)
            last_buf = fp.read(buf_size)

        zero_buf = b"\0" * 1024 * 1024
        self.assertEqual(zero_buf, first_buf, "First 1 MiB was not wiped.")
        self.assertEqual(zero_buf, last_buf, "Last 1 MiB was not wiped.")

    def test_zero_disk_hdd(self):
        tmp_dir = self.make_dir()
        dev_path = (tmp_dir + "/%s").encode("ascii")
        self.patch(maas_wipe, "DEV_PATH", dev_path)
        dev_name = factory.make_name("disk").encode("ascii")
        file_path = dev_path % dev_name
        self.make_empty_file(file_path, content=b"T")
        disk_info = {
            b"supported": True,
            b"enabled": False,
            b"locked": False,
            b"frozen": False,
        }

        # Add a little size to the file making it not evenly
        # divisable by 1 MiB.
        extra_end = 512
        with open(file_path, "a+b") as fp:
            fp.write(b"T" * extra_end)

        zero_disk(dev_name, disk_info)

        zero_buf = b"\0" * 1024 * 1024
        with open(file_path, "rb") as fp:
            fp.seek(0, 2)
            size = fp.tell()
            fp.seek(0, 0)

            count = size // len(zero_buf)
            for i in range(count):
                buf = fp.read(len(zero_buf))
                self.assertEqual(zero_buf, buf, "%d block was not wiped." % i)

            extra_buf = fp.read(extra_end)
            self.assertEqual(
                b"\0" * extra_end, extra_buf, "End was not wiped."
            )

    def patch_args(self, secure_erase, quick_erase):
        args = MagicMock()
        args.secure_erase = secure_erase
        args.quick_erase = quick_erase
        parser = MagicMock()
        parser.parse_args.return_value = args
        self.patch(argparse, "ArgumentParser").return_value = parser

    def test_main_calls_try_secure_erase_for_all_hdd(self):
        self.patch_args(True, False)
        disks = {
            factory.make_name("disk").encode("ascii"): {} for _ in range(3)
        }
        self.patch(maas_wipe, "get_disk_info").return_value = disks

        mock_zero = self.patch(maas_wipe, "zero_disk")
        mock_try = self.patch(maas_wipe, "try_secure_erase")
        mock_try.return_value = True
        maas_wipe.main()

        calls = [call(disk, info) for disk, info in disks.items()]
        self.assertThat(mock_try, MockCallsMatch(*calls))
        self.assertThat(mock_zero, MockNotCalled())

    def test_main_calls_zero_disk_if_no_secure_erase_hdd(self):
        self.patch_args(True, False)
        disks = {
            factory.make_name("disk").encode("ascii"): {} for _ in range(3)
        }
        self.patch(maas_wipe, "get_disk_info").return_value = disks

        mock_zero = self.patch(maas_wipe, "zero_disk")
        mock_try = self.patch(maas_wipe, "try_secure_erase")
        mock_try.return_value = False
        maas_wipe.main()

        try_calls = [call(disk, info) for disk, info in disks.items()]
        self.assertThat(mock_try, MockCallsMatch(*try_calls))
        self.assertThat(mock_zero, MockCallsMatch(*try_calls))

    def test_main_calls_wipe_quickly_if_no_secure_erase_hdd(self):
        self.patch_args(True, True)
        disks = {
            factory.make_name("disk").encode("ascii"): {} for _ in range(3)
        }
        self.patch(maas_wipe, "get_disk_info").return_value = disks

        wipe_quickly = self.patch(maas_wipe, "wipe_quickly")
        mock_try = self.patch(maas_wipe, "try_secure_erase")
        mock_try.return_value = False
        maas_wipe.main()

        try_calls = [call(disk, info) for disk, info in disks.items()]
        wipe_calls = [call(disk) for disk in disks.keys()]
        self.assertThat(mock_try, MockCallsMatch(*try_calls))
        self.assertThat(wipe_quickly, MockCallsMatch(*wipe_calls))

    def test_main_calls_wipe_quickly(self):
        self.patch_args(False, True)
        disks = {
            factory.make_name("disk").encode("ascii"): {} for _ in range(3)
        }
        self.patch(maas_wipe, "get_disk_info").return_value = disks

        wipe_quickly = self.patch(maas_wipe, "wipe_quickly")
        mock_try = self.patch(maas_wipe, "try_secure_erase")
        mock_try.return_value = False
        maas_wipe.main()

        wipe_calls = [call(disk) for disk in disks.keys()]
        self.assertThat(mock_try, MockNotCalled())
        self.assertThat(wipe_quickly, MockCallsMatch(*wipe_calls))

    def test_main_calls_zero_disk(self):
        self.patch_args(False, False)
        disks = {
            factory.make_name("disk").encode("ascii"): {} for _ in range(3)
        }
        self.patch(maas_wipe, "get_disk_info").return_value = disks

        zero_disk = self.patch(maas_wipe, "zero_disk")
        mock_try = self.patch(maas_wipe, "try_secure_erase")
        mock_try.return_value = False
        maas_wipe.main()

        wipe_calls = [call(disk, info) for disk, info in disks.items()]
        self.assertThat(mock_try, MockNotCalled())
        self.assertThat(zero_disk, MockCallsMatch(*wipe_calls))
