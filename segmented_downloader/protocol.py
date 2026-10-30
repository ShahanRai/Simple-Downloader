"""
HTTP Protocol Probe and Header Negotiation.
Implements Range probing, Content-Range inspection, ETag validation, and filename discovery.
Equivalent to IDM's HTTPConnection::RecvAllHeaders and HandleStatus routines.
"""

from dataclasses import dataclass
from typing import Optional, Tuple, Dict
import urllib.request
import urllib.parse
import re
import os


DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


@dataclass
class ProbeResult:
    url: str
    final_url: str
    file_size: int
    accepts_ranges: bool
    filename: str
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    content_type: Optional[str] = None


def extract_filename_from_headers(headers: Dict[str, str], fallback_url: str) -> str:
    """
    Extracts filename from Content-Disposition header if available,
    otherwise infers from URL path.
    """
    cd = headers.get("content-disposition", "")
    if cd:
        # Match filename*=utf-8''... or filename="..."
        match = re.search(r'filename\*=UTF-8\'\'([^;]+)', cd, re.IGNORECASE)
        if match:
            return urllib.parse.unquote(match.group(1))
        match = re.search(r'filename="?([^";]+)"?', cd, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    # Fallback to URL path
    parsed = urllib.parse.urlparse(fallback_url)
    base = os.path.basename(parsed.path)
    if base and "." in base:
        return urllib.parse.unquote(base)
    return "downloaded_file"


def probe_url(url: str, user_agent: str = DEFAULT_USER_AGENT, timeout: int = 15) -> ProbeResult:
    """
    Probes remote server to determine:
    1. Total file size (Content-Length)
    2. Range support (Accept-Ranges: bytes or 206 response to Range header)
    3. ETag and Last-Modified validators
    4. Target filename
    """
    req_headers = {
        "User-Agent": user_agent,
        "Accept": "*/*",
        "Connection": "keep-alive"
    }

    # Step 1: Attempt HEAD request
    head_req = urllib.request.Request(url, headers=req_headers, method="HEAD")
    final_url = url
    file_size = -1
    accepts_ranges = False
    etag = None
    last_modified = None
    content_type = None
    headers_dict = {}

    try:
        with urllib.request.urlopen(head_req, timeout=timeout) as resp:
            final_url = resp.geturl()
            headers_dict = {k.lower(): v for k, v in resp.headers.items()}
            content_length = headers_dict.get("content-length")
            if content_length and content_length.isdigit():
                file_size = int(content_length)

            if headers_dict.get("accept-ranges", "").lower() == "bytes":
                accepts_ranges = True

            etag = headers_dict.get("etag")
            last_modified = headers_dict.get("last-modified")
            content_type = headers_dict.get("content-type")
    except Exception:
        # Some servers reject HEAD requests; fallback to Range byte probe
        pass

    # Step 2: If HEAD was rejected or inconclusive about Range support, send GET Range bytes=0-0
    if not accepts_ranges or file_size <= 0:
        range_headers = req_headers.copy()
        range_headers["Range"] = "bytes=0-0"
        probe_req = urllib.request.Request(url, headers=range_headers, method="GET")

        try:
            with urllib.request.urlopen(probe_req, timeout=timeout) as resp:
                final_url = resp.geturl()
                headers_dict = {k.lower(): v for k, v in resp.headers.items()}
                if resp.status == 206:
                    accepts_ranges = True
                    # Check Content-Range: bytes 0-0/TOTAL
                    content_range = headers_dict.get("content-range", "")
                    match = re.search(r"/(\d+)$", content_range)
                    if match:
                        file_size = int(match.group(1))

                etag = etag or headers_dict.get("etag")
                last_modified = last_modified or headers_dict.get("last-modified")
                content_type = content_type or headers_dict.get("content-type")
        except Exception:
            pass

    filename = extract_filename_from_headers(headers_dict, final_url)

    return ProbeResult(
        url=url,
        final_url=final_url,
        file_size=file_size,
        accepts_ranges=accepts_ranges,
        filename=filename,
        etag=etag,
        last_modified=last_modified,
        content_type=content_type
    )
