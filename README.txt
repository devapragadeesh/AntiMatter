================================================================
  SMART COMPRESSION TOOL — COMMAND REFERENCE
================================================================
  All commands are run from: D:\Engineering\Compression\
================================================================


----------------------------------------------------------------
  1. CHUNKER
     Splits raw 1GB source files into varied-size chunks.
     Run once before anything else.
----------------------------------------------------------------

  # default paths (data/raw → data/chunks)
  python chunker.py

  # custom paths
  python chunker.py --raw_dir path/to/raw --chunks_dir path/to/chunks

  # expected folder structure before running:
  data/raw/
      numeric/     ← excel file here
      random/      ← bin file here
      repetitive/  ← html/text files here
      structured/  ← sql file here
      text/        ← xml file here

  # output goes to:
  data/chunks/
      numeric/
      random/
      repetitive/
      structured/
      text/

  # delete chunks above 50MB (run if pipeline is too slow)
  python -c "
  from pathlib import Path
  chunks_dir = Path('data/chunks')
  deleted = 0
  for f in chunks_dir.rglob('*.bin'):
      if f.stat().st_size / 1024 / 1024 > 50:
          print(f'Deleting {f.name}')
          f.unlink()
          deleted += 1
  print(f'Deleted {deleted} files.')
  "


----------------------------------------------------------------
  2. PROFILER
     Analyzes a file's bytes and returns a feature vector.
     Not run standalone in normal use — called by pipeline.
     Useful for inspecting a single file.
----------------------------------------------------------------

  python profiler.py path/to/file.bin
  python profiler.py data/chunks/text/somechunk.bin


----------------------------------------------------------------
  3. RUNNER
     Compresses a chunk with one engine+level and returns metrics.
     Not run standalone in normal use — called by pipeline.
     Useful for testing a single engine on a single file.
----------------------------------------------------------------

  # test one specific level
  python runner.py path/to/chunk.bin zstd 3

  # test all levels for one engine
  python runner.py path/to/chunk.bin zstd
  python runner.py path/to/chunk.bin brotli
  python runner.py path/to/chunk.bin lzma

  # valid engines:  zstd  lz4  gzip  lzma  brotli
  # zstd levels:    1  3  6  9  12  15  19
  # lz4  levels:    1  3  6  9  12
  # gzip levels:    1  3  6  9
  # lzma levels:    1  3  5  7  9
  # brotli levels:  1  4  7  9  11


----------------------------------------------------------------
  4. PIPELINE
     Runs profiler + runner on every chunk × every engine × level.
     Writes results to benchmark.db. Run once (overnight).
     Safe to ctrl+c and re-run — resumes from where it stopped.
----------------------------------------------------------------

  # default paths
  python pipeline.py

  # custom paths
  python pipeline.py --chunks_dir data/chunks --db data/benchmark.db

  # parallel workers (faster but uses more RAM — careful with lzma)
  python pipeline.py --workers 4

  # dry run — shows what would run without executing
  python pipeline.py --dry_run

  # check progress / failures after run:
  python -c "
  import sqlite3
  conn = sqlite3.connect('data/benchmark.db')
  total   = conn.execute('SELECT COUNT(*) FROM results').fetchone()[0]
  success = conn.execute('SELECT COUNT(*) FROM results WHERE success=1').fetchone()[0]
  failed  = conn.execute('SELECT COUNT(*) FROM results WHERE success=0').fetchone()[0]
  chunks  = conn.execute('SELECT COUNT(DISTINCT chunk_file) FROM results').fetchone()[0]
  print(f'Total: {total}  Success: {success}  Failed: {failed}  Chunks: {chunks}')
  rows = conn.execute('SELECT category, COUNT(DISTINCT chunk_file) FROM results GROUP BY category').fetchall()
  for r in rows: print(f'  {r[0]}: {r[1]} chunks')
  "

  # check failure errors:
  python -c "
  import sqlite3
  conn = sqlite3.connect('data/benchmark.db')
  rows = conn.execute('SELECT chunk_file, engine, level, error FROM results WHERE success=0').fetchall()
  for r in rows: print(r)
  "


----------------------------------------------------------------
  5. COMPRESSOR
     Main tool. Profiles file → selects best engine → compresses.
----------------------------------------------------------------

  -- SMART MODE (recommended) --

  # no constraints — defaults to balanced
  python compressor.py path/to/file.xlsx

  # single constraint
  python compressor.py path/to/file.xlsx --constraint max_compression --degree high
  python compressor.py path/to/file.sql  --constraint max_compression --degree max
  python compressor.py path/to/file.bin  --constraint fast_decompress --degree max
  python compressor.py path/to/file.xml  --constraint fast_compression --degree high
  python compressor.py path/to/file.xlsx --constraint low_memory --degree normal
  python compressor.py path/to/file.xlsx --constraint low_cpu --degree balanced

  # multiple constraints blended
  python compressor.py path/to/file.xlsx --constraint max_compression --degree high --constraint low_memory --degree normal
  python compressor.py path/to/file.xlsx --constraint fast_decompress --degree max --constraint low_memory --degree balanced

  # skip confirmation prompt
  python compressor.py path/to/file.xlsx --constraint balanced --degree high --yes

  # custom output location
  python compressor.py path/to/file.xlsx --output C:/compressed/
  python compressor.py path/to/file.xlsx --output C:/compressed/myfile.xlsx.zst

  -- FORCE MODE (bypass selector) --

  python compressor.py path/to/file.xlsx --engine zstd   --level 9
  python compressor.py path/to/file.xlsx --engine brotli --level 11
  python compressor.py path/to/file.xlsx --engine lzma   --level 9
  python compressor.py path/to/file.xlsx --engine lz4    --level 1

  -- DECOMPRESS --

  # engine auto-detected from extension
  python compressor.py path/to/file.xlsx.zst   --decompress
  python compressor.py path/to/file.sql.br     --decompress
  python compressor.py path/to/file.bin.lz4    --decompress
  python compressor.py path/to/file.xml.gz     --decompress
  python compressor.py path/to/file.xlsx.lzma  --decompress

  # decompress to specific folder
  python compressor.py path/to/file.zst --decompress --output C:/restored/


  -- VALID CONSTRAINTS --
  max_compression    best possible ratio
  balanced           ratio vs speed tradeoff
  fast_compression   compress as fast as possible
  fast_decompress    decompress as fast as possible
  low_cpu            minimize CPU usage
  low_memory         minimize RAM usage

  -- VALID DEGREES --
  normal    (weakest — 0.5x weight)
  balanced  (0.7x weight)
  high      (0.9x weight)
  max       (strongest — 1.0x weight)

  -- OUTPUT FILE EXTENSIONS --
  zstd   → .zst
  lz4    → .lz4
  gzip   → .gz
  lzma   → .lzma
  brotli → .br


----------------------------------------------------------------
  6. VALIDATOR
     Proves the selector is making optimal choices by running
     all engines and comparing where the selector's pick lands.
----------------------------------------------------------------

  # single constraint + degree
  python validator.py path/to/file.xlsx --constraint max_compression --degree high
  python validator.py path/to/file.sql  --constraint fast_decompress --degree max
  python validator.py path/to/file.bin  --constraint low_memory --degree balanced

  # test all 6 constraints at once (takes a while)
  python validator.py path/to/file.xlsx --all_constraints

  # test all 4 degrees for one constraint
  python validator.py path/to/file.xlsx --constraint max_compression --all_degrees
  python validator.py path/to/file.xlsx --constraint balanced --all_degrees
  python validator.py path/to/file.xlsx --constraint low_memory --all_degrees

  # save results to CSV (opens in Excel)
  python validator.py path/to/file.xlsx --all_constraints --csv results.csv
  python validator.py path/to/file.sql  --all_degrees --constraint max_compression --csv results.csv

  -- READING THE RESULTS --
  ✅ OPTIMAL     = rank 1    (selector nailed it)
  ✅ GOOD        = rank 2-3  (top 3, acceptable)
  ⚠️  ACCEPTABLE  = rank 4-5  (close, weights may need tuning)
  ❌ POOR        = rank 6+   (weights need adjusting)

  -- PREDICTION ACCURACY --
  < 10%  ✅ accurate
  < 25%  ⚠️  moderate — DB needs more coverage for this file type
  > 25%  ❌ inaccurate — k-NN not finding similar enough neighbors


----------------------------------------------------------------
  7. VERIFY ENGINES
     Confirm all compression libraries are installed correctly.
----------------------------------------------------------------

  python -c "
  import gzip, lzma, lz4, zstandard, brotli
  print('gzip       stdlib')
  print('lzma       stdlib')
  print('lz4       ', lz4.__version__)
  print('zstandard ', zstandard.__version__)
  print('brotli    ', brotli.__version__)
  print('All engines ready.')
  "


----------------------------------------------------------------
  8. SELECTOR (standalone test)
     Test the selector directly without running compression.
----------------------------------------------------------------

  python selector.py path/to/file.xlsx
  python selector.py path/to/file.sql  --constraint max_compression --degree high
  python selector.py path/to/file.bin  --constraint fast_decompress --degree max
  python selector.py path/to/file.xml  --constraint max_compression --degree high --constraint low_memory --degree normal
  python selector.py path/to/file.xlsx --db path/to/custom/benchmark.db


----------------------------------------------------------------
  9. TUNING WEIGHTS
     Edit CONSTRAINT_WEIGHTS in selector.py
     Current values (update this section when you change them):
----------------------------------------------------------------

  CONSTRAINT_WEIGHTS = {
      #                     ratio  cmp_spd  dcmp_spd  memory
      "max_compression":  [0.90,   0.05,    0.03,    0.02],
      "balanced":         [0.50,   0.20,    0.20,    0.10],
      "fast_compression": [0.10,   0.80,    0.05,    0.05],
      "fast_decompress":  [0.10,   0.05,    0.80,    0.05],
      "low_cpu":          [0.15,   0.65,    0.15,    0.05],
      "low_memory":       [0.10,   0.05,    0.05,    0.80],
  }

  DEGREE_MULTIPLIERS = {
      "normal":   0.50,
      "balanced": 0.70,
      "high":     0.90,
      "max":      1.00,
  }

  After changing weights, re-run validator to confirm improvement:
  python validator.py path/to/file.xlsx --all_constraints


----------------------------------------------------------------
  10. FILE STRUCTURE
----------------------------------------------------------------

  D:\Engineering\Compression\
  │
  ├── chunker.py        splits raw files into chunks
  ├── profiler.py       analyzes file bytes → feature vector
  ├── runner.py         runs one engine+level → measures results
  ├── pipeline.py       orchestrates everything → populates DB
  ├── selector.py       picks best engine from constraints
  ├── compressor.py     main user-facing tool
  ├── validator.py      proves selector choices are optimal
  │
  ├── data/
  │   ├── raw/          original 1GB source files (never modified)
  │   │   ├── numeric/
  │   │   ├── random/
  │   │   ├── repetitive/
  │   │   ├── structured/
  │   │   └── text/
  │   ├── chunks/       generated by chunker.py
  │   └── benchmark.db  generated by pipeline.py
  │
  └── COMMANDS.txt      this file

================================================================