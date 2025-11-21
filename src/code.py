# CircuitPython requires "code.py" to be a non-compiled (source) Python file.
# This file cannot be replaced by a compiled .mpy file, otherwise the board will not boot your code.

import code_support

code_support.main()  # assuming your app has a run() function
