import sys
import json
import base64
import traceback
import io
import os

# =========================
# Standard library (math)
# =========================
import math  # noqa: F401
import cmath  # noqa: F401
import statistics  # noqa: F401
import random  # noqa: F401
import decimal  # noqa: F401
import fractions  # noqa: F401
import itertools  # noqa: F401
import functools  # noqa: F401
import operator  # noqa: F401

# =========================
# Core scientific stack
# =========================
import numpy as np  # noqa: F401
import scipy  # noqa: F401
# import scipy.linalg  # noqa: F401
# import scipy.sparse  # noqa: F401
# import scipy.optimize  # noqa: F401
# import scipy.integrate  # noqa: F401
# import scipy.signal  # noqa: F401
# import scipy.stats  # noqa: F401
# import scipy.fft  # noqa: F401

# =========================
# Symbolic mathematics
# =========================
import sympy as sp  # noqa: F401
# from sympy import symbols  # noqa: F401
# from sympy import Eq  # noqa: F401
# from sympy import solve  # noqa: F401
# from sympy import diff  # noqa: F401
# from sympy import integrate as sp_integrate  # noqa: F401
# from sympy import simplify  # noqa: F401
# from sympy import Matrix  # noqa: F401

# =========================
# High precision math
# =========================
# import mpmath  # noqa: F401


os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"


# Create a persistent namespace for code execution
namespace = {}

# Send ready signal
print(json.dumps({"type": "ready"}))
sys.stdout.flush()

while True:
    try:
        # Read request from stdin
        request_line = sys.stdin.readline()
        if not request_line:
            break

        request = json.loads(request_line)

        if request.get("type") == "exit":
            break

        if request.get("type") == "execute":
            code_b64 = request.get("code", "")
            try:
                code = base64.b64decode(code_b64).decode("utf-8")
            except Exception as e:
                print(
                    json.dumps(
                        {"type": "error", "error": f"Failed to decode code: {str(e)}"}
                    )
                )
                sys.stdout.flush()
                continue

            # Capture stdout
            old_stdout = sys.stdout
            captured_output = io.StringIO()
            sys.stdout = captured_output

            try:
                exec(code, namespace)
                output = captured_output.getvalue()
                sys.stdout = old_stdout
                print(json.dumps({"type": "success", "output": output}))
            except Exception:
                sys.stdout = old_stdout
                error_output = traceback.format_exc()
                print(json.dumps({"type": "error", "error": error_output}))

            sys.stdout.flush()

    except json.JSONDecodeError:
        print(json.dumps({"type": "error", "error": "Invalid JSON"}))
        sys.stdout.flush()
    except Exception as e:
        print(json.dumps({"type": "error", "error": f"Unexpected error: {str(e)}"}))
        sys.stdout.flush()
