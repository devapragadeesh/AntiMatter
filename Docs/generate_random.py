import os

# size in bytes (example: 500MB)
size = 500 * 1024 * 1024

with open("random_500mb.bin", "wb") as f:
    f.write(os.urandom(size))

print("Random file generated.")