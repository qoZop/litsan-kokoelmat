"""
generate_password_hash.py

Run this script to generate a SHA-256 hash for your chosen password.
Paste the output into index.html where PASSWORD_HASH is defined.

Usage:
    python scripts/generate_password_hash.py
"""

import hashlib
import getpass

password = getpass.getpass("Enter password: ")
hash_value = hashlib.sha256(password.encode()).hexdigest()
print(f"\nPassword hash (paste into index.html):\n{hash_value}")
