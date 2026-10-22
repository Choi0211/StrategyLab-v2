# YouTube cookie authentication

`GAON_YOUTUBE_COOKIES_FILE` optionally selects an authorized Netscape-format
cookie file. Without a configured or default file, cookie authentication remains
disabled.

On Linux/POSIX, the file must be a regular non-symlink file with no group or
other permission bits (normally mode `0600`). The permission check runs before
reading cookie contents. The existing format and `youtube.com` content checks
also apply.

On Windows, configured cookie authentication is refused before reading the file.
Python's Windows `chmod(0600)` and `stat()` do not establish a private NTFS ACL;
there is currently no ACL validator in this feature. This refusal also applies
to a discovered default cookie file. Unauthenticated research remains available
subject to the normal provider restrictions.

`tests/unit/test_research_media_tools.py` checks native platform behavior, each
POSIX group/other permission bit, simulated Windows refusal before reading, and
content validation independently of the permission gate. No platform test is
skipped to accommodate this policy. Actual Windows validation runs in the PR's
Windows Python 3.12 GitHub Actions job.
