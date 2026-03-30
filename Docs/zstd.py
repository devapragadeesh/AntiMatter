'''
Tunable Parameters: levels, threads, window size, dictionary

Compression
zstd 'file.txt' 
gives 
'file.txt.zst'

Decompression
zstd -d file.txt.zst
gives
unzstd file.txt.zst

levels between 1 to 19 have good speed vs compression ratio
levels 20 to 22 are high compression
zstd -1 file.txt

Compress without deleting orginal
zstd -k file.txt

Benchmark mode ( very useful )
zstd -b1e22 file.txt

Compression statistics
zstd -v file.txt

Compression ratio
ls -lh file.txt*
'''