# Public HKSC collaboration

This repository is research-only. Do not access accounts, funds, real positions,
orders or trading login state. Do not place, cancel or modify orders.

Keep data_source separate from access_tool. Preserve source timestamps,
retrieval timestamps, adjustment basis, units and file hashes. Missing evidence
must stay missing. Do not silently repair data, switch providers or reinterpret
an unavailable opening price as the current price.

Only synthetic or explicitly redistributable samples may be committed. Keep
credentials, real provider responses, local configurations and generated runs
in ignored local/ or outputs/ directories. Use explicit file staging.

Demo tests establish implementation behavior with fixtures, not live source
availability, strategy profitability or production acceptance. Keep the public
strategy version independent of any privately operated HKSC instance.
