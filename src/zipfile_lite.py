"""
Lightweight ZIP file extraction for CircuitPython.

Implements basic ZIP file parsing and extraction using zlib for decompression.
Supports stored (uncompressed) and deflated files.
"""

import struct
import zlib

from logging_helper import logger
from utils import suppress


class ZipFile:
    """Simple ZIP file reader for CircuitPython."""

    # ZIP file signatures
    LOCAL_FILE_HEADER_SIG = b"PK\x03\x04"
    CENTRAL_DIR_SIG = b"PK\x01\x02"
    END_CENTRAL_DIR_SIG = b"PK\x05\x06"

    # Compression methods
    STORED = 0  # No compression
    DEFLATED = 8  # DEFLATE compression

    def __init__(self, filename):
        """
        Initialize ZIP file reader.

        Args:
            filename: Path to ZIP file
        """
        self.filename = filename
        self.file_list = []
        self.logger = logger("wicid.zipfile")
        self._find_central_directory()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        # Nothing to clean up
        return False

    def _find_central_directory(self):
        """Find and parse the central directory to get file list."""
        with open(self.filename, "rb") as f:
            # Read last 64KB to find end of central directory
            f.seek(0, 2)  # Seek to end
            file_size = f.tell()

            # Read the last part of file (up to 64KB or file size)
            read_size = min(65536, file_size)
            f.seek(file_size - read_size)
            data = f.read(read_size)

            # Find end of central directory signature
            ecd_offset = data.rfind(self.END_CENTRAL_DIR_SIG)
            if ecd_offset == -1:
                raise ValueError("Not a valid ZIP file")

            # Parse end of central directory
            ecd_data = data[ecd_offset:]

            # Structure: signature(4) + disk(2) + disk_start(2) +
            #            num_entries_disk(2) + num_entries(2) +
            #            cd_size(4) + cd_offset(4) + comment_len(2)
            if len(ecd_data) < 22:
                raise ValueError("Corrupt ZIP file")

            num_entries = struct.unpack("<H", ecd_data[10:12])[0]
            cd_size = struct.unpack("<I", ecd_data[12:16])[0]
            cd_offset = struct.unpack("<I", ecd_data[16:20])[0]

            # Read central directory
            f.seek(cd_offset)
            cd_data = f.read(cd_size)

            # Parse central directory entries
            offset = 0
            for _ in range(num_entries):
                if cd_data[offset : offset + 4] != self.CENTRAL_DIR_SIG:
                    break

                # Parse central directory entry
                # signature(4) + version_made(2) + version_needed(2) +
                # flags(2) + compression(2) + mod_time(2) + mod_date(2) +
                # crc32(4) + compressed_size(4) + uncompressed_size(4) +
                # filename_len(2) + extra_len(2) + comment_len(2) +
                # disk_start(2) + internal_attr(2) + external_attr(4) +
                # local_header_offset(4)

                compression = struct.unpack("<H", cd_data[offset + 10 : offset + 12])[0]
                compressed_size = struct.unpack("<I", cd_data[offset + 20 : offset + 24])[0]
                uncompressed_size = struct.unpack("<I", cd_data[offset + 24 : offset + 28])[0]
                filename_len = struct.unpack("<H", cd_data[offset + 28 : offset + 30])[0]
                extra_len = struct.unpack("<H", cd_data[offset + 30 : offset + 32])[0]
                comment_len = struct.unpack("<H", cd_data[offset + 32 : offset + 34])[0]
                local_header_offset = struct.unpack("<I", cd_data[offset + 42 : offset + 46])[0]

                # Extract filename
                filename = cd_data[offset + 46 : offset + 46 + filename_len].decode("utf-8")

                self.file_list.append(
                    {
                        "filename": filename,
                        "compression": compression,
                        "compressed_size": compressed_size,
                        "uncompressed_size": uncompressed_size,
                        "local_header_offset": local_header_offset,
                    }
                )

                # Move to next entry
                offset += 46 + filename_len + extra_len + comment_len

    def namelist(self):
        """Return list of filenames in the ZIP."""
        return [f["filename"] for f in self.file_list]

    def extract(self, member, path="/"):
        """
        Extract a member to the specified path.

        Args:
            member: Filename or file info dict
            path: Destination directory (default: root)
        """
        # Find file info
        if isinstance(member, str):
            file_info = None
            for f in self.file_list:
                if f["filename"] == member:
                    file_info = f
                    break
            if not file_info:
                raise KeyError(f"File not found in ZIP: {member}")
        else:
            file_info = member

        filename = file_info["filename"]

        # Skip directories
        if filename.endswith("/"):
            return

        # Read local file header and data
        with open(self.filename, "rb") as f:
            f.seek(file_info["local_header_offset"])

            # Parse local file header
            # signature(4) + version(2) + flags(2) + compression(2) +
            # mod_time(2) + mod_date(2) + crc32(4) + compressed_size(4) +
            # uncompressed_size(4) + filename_len(2) + extra_len(2)
            header = f.read(30)

            if header[:4] != self.LOCAL_FILE_HEADER_SIG:
                raise ValueError("Invalid local file header")

            filename_len = struct.unpack("<H", header[26:28])[0]
            extra_len = struct.unpack("<H", header[28:30])[0]

            # Skip filename and extra field
            f.seek(filename_len + extra_len, 1)

            # Read compressed data
            compressed_data = f.read(file_info["compressed_size"])

        # Decompress if needed
        if file_info["compression"] == self.STORED:
            data = compressed_data
        elif file_info["compression"] == self.DEFLATED:
            # Use raw DEFLATE decompression
            data = zlib.decompress(compressed_data, -15)
        else:
            raise ValueError(f"Unsupported compression method: {file_info['compression']}")

        # Write file
        dest_path = path.rstrip("/") + "/" + filename

        # Create parent directories if needed
        import os

        dir_path = "/".join(dest_path.split("/")[:-1])
        if dir_path and dir_path != "/":
            with suppress(OSError):
                os.mkdir(dir_path)

        with open(dest_path, "wb") as f:
            f.write(data)

        self.logger.debug(f"Extracted: {filename} ({len(data)} bytes)")

    def extractall(self, path="/"):
        """
        Extract all members to the specified path.

        Args:
            path: Destination directory (default: root)
        """
        for file_info in self.file_list:
            if not file_info["filename"].endswith("/"):
                self.extract(file_info, path)

    def read(self, member):
        """
        Read a member's contents without extracting to disk.

        Args:
            member: Filename to read

        Returns:
            bytes: File contents
        """
        # Find file info
        file_info = None
        for f in self.file_list:
            if f["filename"] == member:
                file_info = f
                break

        if not file_info:
            raise KeyError(f"File not found in ZIP: {member}")

        # Read and decompress
        with open(self.filename, "rb") as f:
            f.seek(file_info["local_header_offset"])
            header = f.read(30)

            if header[:4] != self.LOCAL_FILE_HEADER_SIG:
                raise ValueError("Invalid local file header")

            filename_len = struct.unpack("<H", header[26:28])[0]
            extra_len = struct.unpack("<H", header[28:30])[0]

            f.seek(filename_len + extra_len, 1)
            compressed_data = f.read(file_info["compressed_size"])

        if file_info["compression"] == self.STORED:
            return compressed_data
        elif file_info["compression"] == self.DEFLATED:
            return zlib.decompress(compressed_data, -15)
        else:
            raise ValueError(f"Unsupported compression method: {file_info['compression']}")
