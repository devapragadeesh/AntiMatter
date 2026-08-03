# verify_engines.py
import gzip
import lzma
import lz4.frame
import zstandard
import brotli

print("gzip       ✅", gzip.__version__ if hasattr(gzip, '__version__') else "stdlib")
print("lzma       ✅ stdlib")
print("lz4        ✅", lz4.__version__)
print("zstandard  ✅", zstandard.__version__)
print("brotli     ✅", brotli.__version__)
print("\nAll engines ready.")