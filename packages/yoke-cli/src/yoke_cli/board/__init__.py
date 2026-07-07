"""Client-tier ``yoke board rebuild`` driver.

The board is a per-project generated view. Rebuilding it needs only the data
fetch (``board.data.get`` over the CLI's own transport), the pure render that
ships in ``yoke_contracts.board``, and a local file write. The engine wheel
(``yoke_core``) may be installed everywhere, but this subpackage stays
import-isolated from it so ``yoke board rebuild`` never loads engine code.
"""
