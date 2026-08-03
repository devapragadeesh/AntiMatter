"""PyInstaller entry point — a plain script (not part of the antimatter
package) so it can be run as __main__ while antimatter.main still uses
package-relative imports internally."""
from antimatter.main import main

if __name__ == "__main__":
    main()
