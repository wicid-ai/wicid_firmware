"""Unit tests for zipfile_lite module."""

import struct
import unittest
import zlib
from unittest.mock import patch


class TestZipFileInit(unittest.TestCase):
    """Test ZipFile initialization."""

    def test_init_stores_filename(self) -> None:
        """Verify __init__ stores the filename."""
        with patch("utils.zipfile_lite.ZipFile._find_central_directory"):
            from utils.zipfile_lite import ZipFile

            zf = ZipFile("/test.zip")
            self.assertEqual(zf.filename, "/test.zip")

    def test_init_creates_empty_file_list(self) -> None:
        """Verify __init__ creates empty file list."""
        with patch("utils.zipfile_lite.ZipFile._find_central_directory"):
            from utils.zipfile_lite import ZipFile

            zf = ZipFile("/test.zip")
            self.assertEqual(zf.file_list, [])

    def test_context_manager_enter_returns_self(self) -> None:
        """Verify __enter__ returns self."""
        with patch("utils.zipfile_lite.ZipFile._find_central_directory"):
            from utils.zipfile_lite import ZipFile

            zf = ZipFile("/test.zip")
            self.assertIs(zf.__enter__(), zf)

    def test_context_manager_exit_does_nothing(self) -> None:
        """Verify __exit__ does not raise."""
        with patch("utils.zipfile_lite.ZipFile._find_central_directory"):
            from utils.zipfile_lite import ZipFile

            zf = ZipFile("/test.zip")
            # Should not raise
            zf.__exit__(None, None, None)


class TestZipFileSignatures(unittest.TestCase):
    """Test ZIP file signature constants."""

    def test_local_file_header_signature(self) -> None:
        """Verify LOCAL_FILE_HEADER_SIG is correct."""
        from utils.zipfile_lite import ZipFile

        self.assertEqual(ZipFile.LOCAL_FILE_HEADER_SIG, b"PK\x03\x04")

    def test_central_dir_signature(self) -> None:
        """Verify CENTRAL_DIR_SIG is correct."""
        from utils.zipfile_lite import ZipFile

        self.assertEqual(ZipFile.CENTRAL_DIR_SIG, b"PK\x01\x02")

    def test_end_central_dir_signature(self) -> None:
        """Verify END_CENTRAL_DIR_SIG is correct."""
        from utils.zipfile_lite import ZipFile

        self.assertEqual(ZipFile.END_CENTRAL_DIR_SIG, b"PK\x05\x06")

    def test_compression_method_stored(self) -> None:
        """Verify STORED compression method is 0."""
        from utils.zipfile_lite import ZipFile

        self.assertEqual(ZipFile.STORED, 0)

    def test_compression_method_deflated(self) -> None:
        """Verify DEFLATED compression method is 8."""
        from utils.zipfile_lite import ZipFile

        self.assertEqual(ZipFile.DEFLATED, 8)


class TestNameList(unittest.TestCase):
    """Test namelist() method."""

    def test_namelist_returns_filenames(self) -> None:
        """Verify namelist() returns list of filenames."""
        with patch("utils.zipfile_lite.ZipFile._find_central_directory"):
            from utils.zipfile_lite import ZipFile

            zf = ZipFile("/test.zip")
            zf.file_list = [
                {"filename": "file1.txt", "local_header_offset": 0},
                {"filename": "dir/file2.txt", "local_header_offset": 100},
            ]

            names = zf.namelist()
            self.assertEqual(names, ["file1.txt", "dir/file2.txt"])

    def test_namelist_empty_zip(self) -> None:
        """Verify namelist() returns empty list for empty ZIP."""
        with patch("utils.zipfile_lite.ZipFile._find_central_directory"):
            from utils.zipfile_lite import ZipFile

            zf = ZipFile("/test.zip")
            zf.file_list = []

            self.assertEqual(zf.namelist(), [])


class TestRead(unittest.TestCase):
    """Test read() method."""

    def test_read_raises_for_missing_file(self) -> None:
        """Verify read() raises KeyError for missing file."""
        with patch("utils.zipfile_lite.ZipFile._find_central_directory"):
            from utils.zipfile_lite import ZipFile

            zf = ZipFile("/test.zip")
            zf.file_list = []

            with self.assertRaises(KeyError):
                zf.read("nonexistent.txt")

    def test_read_unsupported_compression_raises(self) -> None:
        """Verify read() raises ValueError for unsupported compression."""
        import io

        name_bytes = b"test.txt"
        header = struct.pack(
            "<4sHHHHHIIIHH",
            b"PK\x03\x04",
            20,
            0,
            12,  # BZIP2 - unsupported
            0,
            0,
            0,
            100,
            100,
            len(name_bytes),
            0,
        )
        file_bytes = header + name_bytes + b"\x00" * 100

        with patch("utils.zipfile_lite.ZipFile._find_central_directory"):
            from utils.zipfile_lite import ZipFile

            zf = ZipFile("/test.zip")
            zf.file_list = [
                {
                    "filename": "test.txt",
                    "local_header_offset": 0,
                    "compression": 12,
                    "compressed_size": 100,
                    "uncompressed_size": 100,
                }
            ]

            # Use BytesIO for proper seek/read behavior
            with patch("builtins.open", return_value=io.BytesIO(file_bytes)):
                with self.assertRaises(ValueError) as ctx:
                    zf.read("test.txt")
                self.assertIn("Unsupported compression", str(ctx.exception))

    def test_read_invalid_header_raises(self) -> None:
        """Verify read() raises ValueError for invalid local file header."""
        import io

        # Invalid header - wrong signature
        file_bytes = b"XXXX" + b"\x00" * 100

        with patch("utils.zipfile_lite.ZipFile._find_central_directory"):
            from utils.zipfile_lite import ZipFile

            zf = ZipFile("/test.zip")
            zf.file_list = [
                {
                    "filename": "test.txt",
                    "local_header_offset": 0,
                    "compression": 0,
                    "compressed_size": 10,
                    "uncompressed_size": 10,
                }
            ]

            with patch("builtins.open", return_value=io.BytesIO(file_bytes)):
                with self.assertRaises(ValueError) as ctx:
                    zf.read("test.txt")
                self.assertIn("Invalid local file header", str(ctx.exception))

    def test_read_stored_file(self) -> None:
        """Verify read() reads stored (uncompressed) file."""
        import io

        content = b"Hello, World!"
        name_bytes = b"test.txt"

        # Build local file header
        header = struct.pack(
            "<4sHHHHHIIIHH",
            b"PK\x03\x04",
            20,  # version
            0,  # flags
            0,  # STORED
            0,
            0,  # time/date
            0,  # crc32
            len(content),
            len(content),
            len(name_bytes),
            0,
        )
        file_bytes = header + name_bytes + content

        with patch("utils.zipfile_lite.ZipFile._find_central_directory"):
            from utils.zipfile_lite import ZipFile

            zf = ZipFile("/test.zip")
            zf.file_list = [
                {
                    "filename": "test.txt",
                    "local_header_offset": 0,
                    "compression": 0,
                    "compressed_size": len(content),
                    "uncompressed_size": len(content),
                }
            ]

            # Use BytesIO for proper seek/read behavior
            with patch("builtins.open", return_value=io.BytesIO(file_bytes)):
                result = zf.read("test.txt")
                self.assertEqual(result, content)

    def test_read_deflated_file(self) -> None:
        """Verify read() decompresses DEFLATE file."""
        import io

        original = b"This is test content that will be compressed"
        # Compress with raw deflate (wbits=-15)
        compressor = zlib.compressobj(level=6, wbits=-15)
        compressed = compressor.compress(original) + compressor.flush()

        name_bytes = b"test.txt"
        header = struct.pack(
            "<4sHHHHHIIIHH",
            b"PK\x03\x04",
            20,
            0,
            8,  # DEFLATED
            0,
            0,
            zlib.crc32(original) & 0xFFFFFFFF,
            len(compressed),
            len(original),
            len(name_bytes),
            0,
        )
        file_bytes = header + name_bytes + compressed

        with patch("utils.zipfile_lite.ZipFile._find_central_directory"):
            from utils.zipfile_lite import ZipFile

            zf = ZipFile("/test.zip")
            zf.file_list = [
                {
                    "filename": "test.txt",
                    "local_header_offset": 0,
                    "compression": 8,
                    "compressed_size": len(compressed),
                    "uncompressed_size": len(original),
                }
            ]

            # Use BytesIO for proper seek/read behavior
            with patch("builtins.open", return_value=io.BytesIO(file_bytes)):
                result = zf.read("test.txt")
                self.assertEqual(result, original)


class TestExtract(unittest.TestCase):
    """Test extract() method."""

    def test_extract_skips_directory_entries(self) -> None:
        """Verify extract() returns early for directory entries."""
        with patch("utils.zipfile_lite.ZipFile._find_central_directory"):
            from utils.zipfile_lite import ZipFile

            zf = ZipFile("/test.zip")
            file_info = {"filename": "somedir/", "local_header_offset": 0}
            zf.file_list = [file_info]

            # Should not raise, should just return
            with patch("builtins.open") as mock_file:
                zf.extract(file_info, "/output")
                # open should not be called for directory extraction
                mock_file.assert_not_called()

    def test_extract_raises_for_missing_file(self) -> None:
        """Verify extract() raises KeyError when file not found."""
        with patch("utils.zipfile_lite.ZipFile._find_central_directory"):
            from utils.zipfile_lite import ZipFile

            zf = ZipFile("/test.zip")
            zf.file_list = []

            with self.assertRaises(KeyError) as ctx:
                zf.extract("nonexistent.txt", "/output")
            self.assertIn("File not found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
